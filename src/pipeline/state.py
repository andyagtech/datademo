"""
Immutable Pipeline State for Functional Pipeline Architecture

Replaces the mutable PipelineContext with immutable, typed state
that flows through the pipeline as a value.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, final

from src.functional import Result, Success, Maybe, Some, Nothing
from src.pipeline.receive_pure import ReceiveResult


@final
@dataclass(frozen=True, slots=True)
class StepOutcome:
    """
    Immutable outcome of a single pipeline step.
    
    Replaces mutable StepResult with frozen data.
    """
    step_name: str
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    
    @classmethod
    def ok(
        cls,
        step_name: str,
        message: str,
        data: dict[str, Any] | None = None
    ) -> StepOutcome:
        """Create successful outcome."""
        return cls(
            step_name=step_name,
            success=True,
            message=message,
            data=data or {},
        )
    
    @classmethod
    def err(
        cls,
        step_name: str,
        message: str,
        errors: tuple[str, ...],
        warnings: tuple[str, ...] = ()
    ) -> StepOutcome:
        """Create failed outcome."""
        return cls(
            step_name=step_name,
            success=False,
            message=message,
            errors=errors,
            warnings=warnings,
        )
    
    def add_warning(self, warning: str) -> StepOutcome:
        """Return new outcome with added warning."""
        return replace(
            self,
            warnings=self.warnings + (warning,)
        )


@final
@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """
    Immutable pipeline configuration.
    
    All parameters for pipeline execution, frozen at start.
    """
    old_data_dir: Path
    new_data_dir: Maybe[Path] = field(default_factory=Nothing)
    db_path: Maybe[Path] = field(default_factory=Nothing)
    skip_ingest: bool = False
    mode: str = "local"  # "local" or "cloud"
    
    # Validation thresholds
    expected_beneficiary_files: int = 3
    expected_carrier_files: int = 2


@final
@dataclass(frozen=True, slots=True)
class PipelineState:
    """
    Immutable state flowing through the pipeline.
    
    Each step returns a new PipelineState - no mutation.
    The state captures all information needed for downstream steps.
    """
    # Configuration (immutable)
    config: PipelineConfig
    
    # Accumulated step outcomes (immutable tuple)
    outcomes: tuple[StepOutcome, ...] = field(default_factory=tuple)
    
    # Step-specific results (typed data classes, not dicts)
    receive_result: Maybe[ReceiveResult] = field(default_factory=Nothing)
    # schema_result: Maybe[SchemaValidationResult] = field(default_factory=Nothing)
    # ingest_result: Maybe[IngestResult] = field(default_factory=Nothing)
    # match_result: Maybe[MatchResult] = field(default_factory=Nothing)
    # compare_result: Maybe[CompareResult] = field(default_factory=Nothing)
    # report_result: Maybe[ReportResult] = field(default_factory=Nothing)
    
    # Status
    halted: bool = False
    halt_reason: str = ""
    
    # DB connection (not stored in state - passed separately)
    # This maintains purity while allowing DB operations
    
    def with_outcome(self, outcome: StepOutcome) -> PipelineState:
        """Return new state with added outcome."""
        new_outcomes = self.outcomes + (outcome,)
        
        # Auto-set halted on failure
        halted = self.halted or not outcome.success
        halt_reason = self.halt_reason
        if halted and not self.halted:
            halt_reason = outcome.message
        
        return replace(
            self,
            outcomes=new_outcomes,
            halted=halted,
            halt_reason=halt_reason
        )
    
    def with_receive(self, result: ReceiveResult) -> PipelineState:
        """Return new state with receive result."""
        return replace(self, receive_result=Some(result))
    
    def should_halt(self) -> bool:
        """Check if pipeline should stop."""
        return self.halted
    
    def get_last_outcome(self) -> Maybe[StepOutcome]:
        """Get most recent outcome."""
        if not self.outcomes:
            return Nothing()
        return Some(self.outcomes[-1])
    
    def get_step_outcome(self, step_name: str) -> Maybe[StepOutcome]:
        """Find outcome by step name."""
        for o in self.outcomes:
            if o.step_name == step_name:
                return Some(o)
        return Nothing()
    
    @property
    def success_count(self) -> int:
        """Count successful steps."""
        return sum(1 for o in self.outcomes if o.success)
    
    @property
    def total_count(self) -> int:
        """Total completed steps."""
        return len(self.outcomes)
    
    @property
    def all_succeeded(self) -> bool:
        """Check if all steps so far succeeded."""
        return all(o.success for o in self.outcomes)


# Railway-oriented pipeline execution
def step_wrapper(
    step_name: str,
    step_fn: Any,  # Function that takes state and returns Result[state, error]
) -> Callable[[PipelineState], Result[PipelineState, Exception]]:
    """
    Higher-order function: Wraps a step for railway-oriented execution.
    
    Usage:
        pipeline = (
            initial_state
            |> step_wrapper("receive", receive_step)
            |> bind(step_wrapper("schema", schema_step))
            |> bind(step_wrapper("ingest", ingest_step))
        )
    """
    def wrapped(state: PipelineState) -> Result[PipelineState, Exception]:
        # Check if already halted
        if state.should_halt():
            return Success(state)
        
        # Execute step
        result = step_fn(state)
        
        if result.is_err:
            # Convert to outcome and return new state
            err = result.unwrap()
            outcome = StepOutcome.err(
                step_name=step_name,
                message=str(err),
                errors=(str(err),)
            )
            return Success(state.with_outcome(outcome))
        
        # Step succeeded
        return result
    
    return wrapped


# Type aliases for step functions
StepFunction = Callable[[PipelineState], Result[PipelineState, Exception]]
Pipeline = Callable[[PipelineState], Result[PipelineState, Exception]]


def compose_pipeline(*steps: StepFunction) -> Pipeline:
    """
    Compose multiple steps into a pipeline.
    
    Each step receives state and returns Result[state, error].
    Failures short-circuit the pipeline.
    
    Usage:
        pipeline = compose_pipeline(
            step_wrapper("receive", receive_step),
            step_wrapper("schema", schema_step),
            step_wrapper("ingest", ingest_step),
        )
        
        final_state = pipeline(initial_state).unwrap()
    """
    def pipeline(initial_state: PipelineState) -> Result[PipelineState, Exception]:
        state = initial_state
        
        for step in steps:
            result = step(state)
            
            if result.is_err:
                return result
            
            state = result.unwrap()
            
            # Check for halt after each step
            if state.should_halt():
                break
        
        return Success(state)
    
    return pipeline


__all__ = [
    "StepOutcome",
    "PipelineConfig",
    "PipelineState",
    "step_wrapper",
    "compose_pipeline",
    "StepFunction",
    "Pipeline",
]
