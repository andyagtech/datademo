"""
Functional Programming Utilities for CMS Claims Pipeline

Thin compatibility layer over the `returns` library (dry-python/returns).
Provides railway-oriented Result/Maybe types plus project-specific helpers.

Library: https://github.com/dry-python/returns
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, TypeVar, ParamSpec, Any
from functools import wraps, reduce
import logging

# Re-export core types from returns
from returns.result import Result, Success, Failure
from returns.maybe import Maybe, Some, Nothing
from returns.pipeline import flow
from returns.functions import tap

logger = logging.getLogger(__name__)

T = TypeVar("T")
U = TypeVar("U")
E = TypeVar("E")
P = ParamSpec("P")


# ---------------------------------------------------------------------------
# Compatibility aliases
# ---------------------------------------------------------------------------

def pipe(value: T, *functions: Callable) -> T:
    """Left-to-right composition. Alias for returns.pipeline.flow."""
    return flow(value, *functions)


def compose(*functions: Callable) -> Callable:
    """Right-to-left function composition."""
    return lambda x: reduce(lambda v, f: f(v), reversed(functions), x)


def when(pred: Callable[[T], bool], f: Callable[[T], T]) -> Callable[[T], T]:
    """Conditional transformation: apply f only if pred is true."""
    def wrapper(x: T) -> T:
        return f(x) if pred(x) else x
    return wrapper


def unless(pred: Callable[[T], bool], f: Callable[[T], T]) -> Callable[[T], T]:
    """Conditional transformation (inverted): apply f only if pred is false."""
    def wrapper(x: T) -> T:
        return x if pred(x) else f(x)
    return wrapper


# ---------------------------------------------------------------------------
# Result/Maybe helpers bridging returns API to our conventions
# ---------------------------------------------------------------------------

def try_op(f: Callable[[], T]) -> Result[T, Exception]:
    """Wrap a callable in try/catch, returning Result."""
    try:
        return Success(f())
    except Exception as e:
        logger.exception("Operation failed")
        return Failure(e)


def is_ok(result: Result) -> bool:
    """Check if a Result is Success."""
    return isinstance(result, Success)


def is_err(result: Result) -> bool:
    """Check if a Result is Failure."""
    return isinstance(result, Failure)


def is_some(maybe: Maybe) -> bool:
    """Check if a Maybe is Some."""
    return isinstance(maybe, Some)


def is_nothing(maybe: Maybe) -> bool:
    """Check if a Maybe is Nothing."""
    return maybe is Nothing


# ---------------------------------------------------------------------------
# Project-specific error handling
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PipelineError:
    """Structured error for pipeline operations."""
    step: str
    message: str
    cause: Exception | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        base = f"[{self.step}] {self.message}"
        if self.cause:
            base += f" (caused by: {self.cause})"
        return base


def catch_as_result(
    step_name: str,
) -> Callable[[Callable[P, T]], Callable[P, Result[T, PipelineError]]]:
    """
    Decorator: convert exceptions to Result[T, PipelineError].

    @catch_as_result("ingest")
    def ingest_files(config: IngestConfig) -> IngestResult:
        ...
    """
    def decorator(f: Callable[P, T]) -> Callable[P, Result[T, PipelineError]]:
        @wraps(f)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> Result[T, PipelineError]:
            try:
                return Success(f(*args, **kwargs))
            except Exception as e:
                return Failure(PipelineError(
                    step=step_name,
                    message=str(e),
                    cause=e,
                ))
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Lazy evaluation
# ---------------------------------------------------------------------------

def lazy(f: Callable[[], T]) -> Callable[[], T]:
    """
    Deferred evaluation with memoisation.

    expensive = lazy(lambda: compute_expensive())
    value = expensive()  # Only computed on first call
    """
    cache: list[T] = []
    def wrapper() -> T:
        if not cache:
            cache.append(f())
        return cache[0]
    return wrapper


__all__ = [
    # Re-exported from returns
    "Result", "Success", "Failure",
    "Maybe", "Some", "Nothing",
    "flow", "tap",
    # Compatibility / helpers
    "pipe", "compose", "when", "unless",
    "try_op", "is_ok", "is_err", "is_some", "is_nothing",
    # Project-specific
    "PipelineError", "catch_as_result", "lazy",
]
