"""
Pattern Matching with Monadic Types (Python 3.14+)

Demonstrates structural pattern matching on Result/Maybe/domain types.
This is the Pythonic equivalent of Haskell/Scala case expressions.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.functional import (
    Result, Success, Failure, Maybe, Some,
    PipelineError, is_nothing,
)
from src.pipeline.receive_pure import ReceiveResult, FileInventory
from src.pipeline.schema_validate_pure import (
    FileType, SchemaValidationResult,
)


# ---------------------------------------------------------------------------
# Result pattern matching
# ---------------------------------------------------------------------------

def describe_result[T, E](result: Result[T, E]) -> str:
    """
    Pattern match on Result to produce a human-readable description.

    Uses Python 3.14 generic syntax (PEP 695) in the signature
    and structural pattern matching (PEP 634) in the body.
    """
    match result:
        case Success(value):
            return f"Success: {value}"
        case Failure(error):
            return f"Failure: {error}"


def handle_pipeline_error(result: Result[str, PipelineError]) -> str:
    """
    Pattern match on structured PipelineError inside a Failure.

    Demonstrates nested destructuring — matching on the error's fields.
    """
    match result:
        case Success(value):
            return f"OK: {value}"
        case Failure(PipelineError(step="receive", message=msg)):
            return f"Receive failed: {msg}"
        case Failure(PipelineError(step="schema_validate", message=msg)):
            return f"Schema invalid: {msg}"
        case Failure(PipelineError(step=step, message=msg, cause=cause)) if cause is not None:
            return f"[{step}] {msg} (caused by {type(cause).__name__})"
        case Failure(PipelineError(step=step, message=msg)):
            return f"[{step}] {msg}"
        case Failure(err):
            return f"Unknown error: {err}"


# ---------------------------------------------------------------------------
# Maybe pattern matching
# ---------------------------------------------------------------------------

def maybe_to_str[T](maybe: Maybe[T], default: str = "<empty>") -> str:
    """Pattern match on Maybe with a default for Nothing."""
    match maybe:
        case Some(value):
            return str(value)
        case nothing if is_nothing(nothing):
            return default


def lookup_file(inventory: FileInventory, name: str) -> str:
    """Pattern match on Maybe result of inventory lookup."""
    match inventory.get(name):
        case Some(file_info):
            return f"Found {file_info.name} ({file_info.size_mb} MB, sha256={file_info.sha256[:8]}...)"
        case nothing if is_nothing(nothing):
            return f"File '{name}' not found in inventory"


# ---------------------------------------------------------------------------
# Domain type matching — FileType as algebraic data type
# ---------------------------------------------------------------------------

def describe_file_type(ft: FileType) -> str:
    """
    Pattern match on FileType.kind as a discriminated union.

    In Haskell this would be:
      describeFileType :: FileType -> String
      describeFileType (FileType "beneficiary")    = "Beneficiary Summary"
      describeFileType (FileType "carrier_claims") = "Carrier Claims"
      describeFileType _                           = "Unknown file type"
    """
    match ft:
        case FileType(kind="beneficiary"):
            return "Beneficiary Summary"
        case FileType(kind="carrier_claims"):
            return "Carrier Claims"
        case FileType(kind=k):
            return f"Unknown file type ({k})"


def summarize_validation(result: Result[SchemaValidationResult, Exception]) -> str:
    """Pattern match to summarize schema validation outcome."""
    match result:
        case Failure(exc):
            return f"Validation error: {exc}"
        case Success(sv) if sv.all_valid:
            return f"All {sv.total_count} files valid ✓"
        case Success(sv):
            invalid = [v for v in sv.validations if not v.valid]
            return (
                f"{sv.valid_count}/{sv.total_count} valid, "
                f"{len(invalid)} invalid: {[v.file_name for v in invalid]}"
            )


# ---------------------------------------------------------------------------
# Multi-level matching — combining Result + domain types
# ---------------------------------------------------------------------------

def receive_summary(result: Result[ReceiveResult, Exception]) -> str:
    """
    Deep pattern match combining Result with domain-level conditions.

    Demonstrates the power of nested matching for error classification.
    """
    match result:
        case Failure(FileNotFoundError() as e):
            return f"Directory missing: {e}"
        case Failure(PermissionError() as e):
            return f"Permission denied: {e}"
        case Failure(exc):
            return f"Unexpected error: {type(exc).__name__}: {exc}"
        case Success(ReceiveResult(missing_categories=m)) if len(m) == 0:
            return "All files received ✓"
        case Success(ReceiveResult(missing_categories=missing)):
            return f"Incomplete: missing {list(missing)}"


# ---------------------------------------------------------------------------
# Guard clauses with pattern matching
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Threshold:
    """Configurable threshold for file count validation."""
    min_files: int
    warn_below: int

    def check(self, count: int) -> str:
        match (count >= self.min_files, count >= self.warn_below):
            case (True, True):
                return "OK"
            case (True, False):
                return "WARNING"  # pragma: no cover (unreachable if warn_below >= min_files)
            case (False, _):
                return "FAIL"


__all__ = [
    "describe_result",
    "handle_pipeline_error",
    "maybe_to_str",
    "lookup_file",
    "describe_file_type",
    "summarize_validation",
    "receive_summary",
    "Threshold",
]
