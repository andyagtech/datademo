"""
Functional Pipeline Runner — Railway-Oriented Execution

Replaces the imperative for-loop with compose_pipeline.
Pure steps (1, 2) run natively; imperative steps (3-6) are
wrapped with legacy_adapter at the boundary.

This is the "functional shell, imperative core" architecture:
  PipelineState flows immutably through composed steps,
  while legacy steps mutate PipelineContext behind an adapter.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from returns.result import Result

from src.functional import Success, is_err, is_ok
from src.pipeline import PipelineContext, StepResult
from src.pipeline.state import (
    PipelineConfig, PipelineState, StepOutcome,
    StepFunction, compose_pipeline,
)
from returns.maybe import Some, Nothing

logger = logging.getLogger("pipeline")


# ---------------------------------------------------------------------------
# Legacy adapter: wraps an imperative step(ctx) -> StepResult
# into a functional StepFunction(state) -> Result[state, Exception]
# ---------------------------------------------------------------------------

def legacy_adapter(
    step_name: str,
    step_fn: Callable[[PipelineContext], StepResult],
    ctx: PipelineContext,
) -> StepFunction:
    """
    Bridge an imperative step into the functional pipeline.

    Closes over the mutable PipelineContext so the legacy step
    can read/write ctx.results, ctx.con, etc.  Converts the
    StepResult back into an immutable StepOutcome on PipelineState.
    """
    def adapted(state: PipelineState) -> Result[PipelineState, Exception]:
        if state.should_halt():
            return Success(state)

        t0 = time.time()
        logger.info("=" * 60)
        logger.info(f"STEP {step_name}")
        logger.info("=" * 60)

        try:
            result: StepResult = step_fn(ctx)
        except Exception as exc:
            elapsed = time.time() - t0
            logger.error(f"  ✗ {step_name} raised: {exc} ({elapsed:.1f}s)")
            outcome = StepOutcome.err(
                step_name=result_step_name(step_name),
                message=str(exc),
                errors=(str(exc),),
            )
            return Success(state.with_outcome(outcome))

        elapsed = time.time() - t0
        status = "✓" if result.success else "✗"
        logger.info(f"  {status} {result.message} ({elapsed:.1f}s)")
        for w in result.warnings:
            logger.warning(f"  ⚠ {w}")
        for e in result.errors:
            logger.error(f"  ✗ {e}")

        outcome = StepOutcome(
            step_name=result.step_name,
            success=result.success,
            message=result.message,
            data=result.data,
            errors=tuple(result.errors),
            warnings=tuple(result.warnings),
        )

        new_state = state.with_outcome(outcome)

        if not result.success:
            logger.error(f"Step {step_name} failed. Pipeline halted.")

        return Success(new_state)

    return adapted


def result_step_name(display_name: str) -> str:
    """Extract a short step name from '3. Ingest & Profile'."""
    return display_name.split(". ", 1)[-1].lower().replace(" & ", "_").replace(" ", "_")


# ---------------------------------------------------------------------------
# Pure step adapters (Steps 1 & 2 — no PipelineContext needed)
# ---------------------------------------------------------------------------

def step1_functional(state: PipelineState) -> Result[PipelineState, Exception]:
    """Step 1: Receive — fully functional."""
    from src.pipeline.receive_pure import (
        receive_old_system_pure, receive_new_system_pure,
    )

    if state.should_halt():
        return Success(state)

    t0 = time.time()
    logger.info("=" * 60)
    logger.info("STEP 1. Receive & Verify")
    logger.info("=" * 60)

    errors: list[str] = []
    warnings: list[str] = []

    # Old system
    old_result = receive_old_system_pure(state.config.old_data_dir)
    if is_err(old_result):
        errors.append(f"Old system receive failed: {old_result.failure()}")
        old_dict: dict = {}
    else:
        recv = old_result.unwrap()
        old_dict = recv.to_legacy_dict()
        if not recv.is_complete:
            errors.append(
                f"Missing old system files: {list(recv.missing_categories)}"
            )

    # New system (optional)
    new_dict: dict | None = None
    match state.config.new_data_dir:
        case Some(new_dir):
            new_result = receive_new_system_pure(new_dir)
            if is_err(new_result):
                errors.append(str(new_result.failure()))
            else:
                new_recv = new_result.unwrap()
                new_dict = new_recv.to_legacy_dict()
                if not new_recv.is_complete:
                    warnings.append(
                        f"New system data incomplete: "
                        f"beneficiary={new_recv.has_beneficiary}, "
                        f"claims={new_recv.has_claims}"
                    )
        case _:
            pass

    elapsed = time.time() - t0
    total_files = len(old_dict.get("inventory", {}))
    if new_dict and "inventory" in new_dict:
        total_files += len(new_dict["inventory"])

    success = len(errors) == 0
    status = "✓" if success else "✗"
    logger.info(f"  {status} Received {total_files} CSV files ({elapsed:.1f}s)")
    for w in warnings:
        logger.warning(f"  ⚠ {w}")
    for e in errors:
        logger.error(f"  ✗ {e}")

    outcome = StepOutcome(
        step_name="receive",
        success=success,
        message=f"Received {total_files} CSV files",
        data={"old_system": old_dict, "new_system": new_dict},
        errors=tuple(errors),
        warnings=tuple(warnings),
    )

    new_state = state.with_outcome(outcome)
    if is_ok(old_result):
        new_state = new_state.with_receive(old_result.unwrap())

    return Success(new_state)


def step2_functional(state: PipelineState) -> Result[PipelineState, Exception]:
    """Step 2: Schema Validate — fully functional."""
    from src.pipeline.schema_validate_pure import schema_validate_pure

    if state.should_halt():
        return Success(state)

    t0 = time.time()
    logger.info("=" * 60)
    logger.info("STEP 2. Schema Validate")
    logger.info("=" * 60)

    # Extract directories from state
    old_system_dir = state.config.old_data_dir / "old_system"

    match state.config.new_data_dir:
        case Some(new_dir):
            new_system_dir = new_dir
        case _:
            new_system_dir = None

    result = schema_validate_pure(old_system_dir, new_system_dir)

    if is_err(result):
        elapsed = time.time() - t0
        msg = f"Schema validation failed: {result.failure()}"
        logger.error(f"  ✗ {msg} ({elapsed:.1f}s)")
        outcome = StepOutcome.err("schema_validate", msg, (msg,))
        return Success(state.with_outcome(outcome))

    sv = result.unwrap()
    elapsed = time.time() - t0

    errors: list[str] = []
    warnings: list[str] = list(sv.all_warnings)

    for v in sv.validations:
        if not v.valid:
            errors.append(f"File invalid: {v.file_name} — {list(v.errors)}")

    if sv.unknown_files:
        warnings.append(
            f"{len(sv.unknown_files)} file(s) could not be classified: "
            f"{[v.file_name for v in sv.unknown_files]}"
        )

    success = len(errors) == 0
    msg = (
        f"Validated {sv.valid_count}/{sv.total_count} files "
        f"({len(sv.beneficiary_files)} beneficiary, "
        f"{len(sv.carrier_files)} carrier claims)"
    )
    status = "✓" if success else "✗"
    logger.info(f"  {status} {msg} ({elapsed:.1f}s)")
    for w in warnings:
        logger.warning(f"  ⚠ {w}")
    for e in errors:
        logger.error(f"  ✗ {e}")

    outcome = StepOutcome(
        step_name="schema_validate",
        success=success,
        message=msg,
        data=sv.to_legacy_dict(),
        errors=tuple(errors),
        warnings=tuple(warnings),
    )

    return Success(state.with_outcome(outcome))


# ---------------------------------------------------------------------------
# Public API: run_pipeline_fp
# ---------------------------------------------------------------------------

def run_pipeline_fp(ctx: PipelineContext) -> list[StepResult]:
    """
    Execute the 6-step pipeline using functional composition.

    All 6 steps are now functional:
      - Steps 1-2: pure functions (no DB dependency)
      - Steps 3-6: interpreter pattern (pure plans + effectful execution)
      - Steps 4-5: Z-set algebra for record matching and comparison

    Returns list[StepResult] for backwards compatibility with main.py.
    """
    from src.pipeline.steps_fp import (
        step3_functional, step4_functional,
        step5_functional, step6_functional,
    )

    # Build immutable config from mutable context
    config = PipelineConfig(
        old_data_dir=ctx.old_data_dir,
        new_data_dir=Some(ctx.new_data_dir) if ctx.new_data_dir else Nothing,
        db_path=Some(ctx.db_path) if ctx.db_path else Nothing,
        skip_ingest=ctx.skip_ingest,
        mode=ctx.mode,
    )
    initial = PipelineState(config=config)

    t_start = time.time()

    # Compose the pipeline: all functional steps
    pipeline = compose_pipeline(
        step1_functional,
        step2_functional,
        step3_functional(ctx),
        step4_functional(ctx),
        step5_functional(ctx),
        step6_functional(ctx),
    )

    # Execute the composed pipeline
    final_result = pipeline(initial)

    # Extract final state
    if is_err(final_result):
        logger.error(f"Pipeline failed: {final_result.failure()}")
        final_state = initial
    else:
        final_state = final_result.unwrap()

    # Sync halted status back to ctx for main.py compatibility
    ctx.halted = final_state.halted
    ctx.halt_reason = final_state.halt_reason

    # Sync receive results into ctx for downstream imperative steps
    for outcome in final_state.outcomes:
        if outcome.data:
            ctx.results[outcome.step_name] = outcome.data

    elapsed = time.time() - t_start
    logger.info("=" * 60)
    logger.info(
        f"Pipeline: {final_state.success_count}/{6} steps completed "
        f"in {elapsed:.1f}s"
    )

    if final_state.halted:
        logger.error(f"Halted: {final_state.halt_reason}")
    else:
        report_data = ctx.results.get("report", {})
        if "report_path" in report_data:
            logger.info(f"Report: {report_data['report_path']}")

    logger.info("=" * 60)

    # Convert outcomes to StepResults for backwards compatibility
    return [
        StepResult(
            step_name=o.step_name,
            success=o.success,
            message=o.message,
            data=o.data,
            errors=list(o.errors),
            warnings=list(o.warnings),
        )
        for o in final_state.outcomes
    ]
