"""
Functional Programming Utilities for CMS Claims Pipeline

Railway-oriented programming with Result types, Maybe types,
and functional composition utilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Generic, TypeVar, ParamSpec, Any, final
from functools import reduce, wraps
import logging

logger = logging.getLogger(__name__)

T = TypeVar("T")
U = TypeVar("U")
E = TypeVar("E")
P = ParamSpec("P")


@final
@dataclass(frozen=True, slots=True)
class Result(Generic[T, E]):
    """
    Railway-oriented programming Result type.
    
    Represents either Success with a value, or Failure with an error.
    Immutable and thread-safe.
    
    Usage:
        result: Result[int, str] = Success(42)
        result = Failure("error message")
        
        # Chain operations
        result.map(lambda x: x * 2).bind(validate)
    """
    _value: T | None = None
    _error: E | None = None
    
    def __post_init__(self) -> None:
        if (self._value is None and self._error is None) or \
           (self._value is not None and self._error is not None):
            raise ValueError("Result must have exactly one of value or error")
    
    @property
    def is_ok(self) -> bool:
        """True if this is a Success."""
        return self._error is None
    
    @property
    def is_err(self) -> bool:
        """True if this is a Failure."""
        return self._error is not None
    
    def map(self, f: Callable[[T], U]) -> Result[U, E]:
        """
        Transform success value. Passes through errors unchanged.
        
        Result(5).map(lambda x: x * 2) == Result(10)
        Failure("err").map(lambda x: x * 2) == Failure("err")
        """
        if self.is_err:
            return Result(_error=self._error)
        return Result(_value=f(self._value))  # type: ignore
    
    def map_err(self, f: Callable[[E], U]) -> Result[T, U]:
        """
        Transform error value. Passes through successes unchanged.
        """
        if self.is_ok:
            return Result(_value=self._value)
        return Result(_error=f(self._error))  # type: ignore
    
    def bind(self, f: Callable[[T], Result[U, E]]) -> Result[U, E]:
        """
        Monadic bind: chain operations that can fail.
        
        result.bind(validate).bind(process).bind(save)
        """
        if self.is_err:
            return Result(_error=self._error)
        return f(self._value)  # type: ignore
    
    def and_then(self, f: Callable[[T], U]) -> Result[U, E]:
        """Alias for map."""
        return self.map(f)
    
    def or_else(self, f: Callable[[E], T]) -> Result[T, E]:
        """
        Provide fallback for failures. Passes through successes.
        """
        if self.is_ok:
            return Result(_value=self._value)
        try:
            return Result(_value=f(self._error))  # type: ignore
        except Exception as e:
            return Result(_error=cast(E, f"Fallback failed: {e}"))
    
    def unwrap(self) -> T:
        """Get value or raise if error."""
        if self.is_err:
            raise ValueError(f"Cannot unwrap failure: {self._error}")
        return self._value  # type: ignore
    
    def unwrap_or(self, default: T) -> T:
        """Get value or return default."""
        return self._value if self.is_ok else default  # type: ignore
    
    def unwrap_or_else(self, f: Callable[[E], T]) -> T:
        """Get value or compute from error."""
        return self._value if self.is_ok else f(self._error)  # type: ignore
    
    def expect(self, msg: str) -> T:
        """Get value or raise with custom message."""
        if self.is_err:
            raise ValueError(f"{msg}: {self._error}")
        return self._value  # type: ignore
    
    def to_optional(self) -> T | None:
        """Convert to Optional. Loses error information."""
        return self._value
    
    @classmethod
    def from_exception(cls, f: Callable[[], T]) -> Result[T, Exception]:
        """Wrap a potentially throwing function."""
        try:
            return Success(f())
        except Exception as e:
            return Failure(e)


def Success(value: T) -> Result[T, Any]:
    """Create a success Result."""
    return Result(_value=value)


def Failure(error: E) -> Result[Any, E]:
    """Create a failure Result."""
    return Result(_error=error)


@final
@dataclass(frozen=True, slots=True)
class Maybe(Generic[T]):
    """
    Maybe/Option type for nullable values.
    
    Explicit representation of presence/absence, avoiding None.
    """
    _value: T | None = None
    _is_some: bool = False
    
    def __post_init__(self) -> None:
        if self._is_some and self._value is None:
            raise ValueError("Some cannot have None value")
    
    @property
    def is_some(self) -> bool:
        """True if has value."""
        return self._is_some
    
    @property
    def is_nothing(self) -> bool:
        """True if empty."""
        return not self._is_some
    
    def map(self, f: Callable[[T], U]) -> Maybe[U]:
        """Transform if has value."""
        if self.is_nothing:
            return Nothing()
        return Some(f(self._value))  # type: ignore
    
    def bind(self, f: Callable[[T], Maybe[U]]) -> Maybe[U]:
        """Chain Maybe-returning operations."""
        if self.is_nothing:
            return Nothing()
        return f(self._value)  # type: ignore
    
    def filter(self, pred: Callable[[T], bool]) -> Maybe[T]:
        """Keep value only if predicate true."""
        if self.is_nothing or not pred(self._value):  # type: ignore
            return Nothing()
        return self
    
    def unwrap(self) -> T:
        """Get value or raise."""
        if self.is_nothing:
            raise ValueError("Cannot unwrap Nothing")
        return self._value  # type: ignore
    
    def unwrap_or(self, default: T) -> T:
        """Get value or default."""
        return self._value if self.is_some else default  # type: ignore
    
    def unwrap_or_else(self, f: Callable[[], T]) -> T:
        """Get value or compute default."""
        return self._value if self.is_some else f()
    
    def to_result(self, err: E) -> Result[T, E]:
        """Convert to Result with provided error."""
        if self.is_some:
            return Success(self._value)  # type: ignore
        return Failure(err)
    
    @classmethod
    def from_optional(cls, val: T | None) -> Maybe[T]:
        """Convert from Optional."""
        return Some(val) if val is not None else Nothing()


def Some(value: T) -> Maybe[T]:
    """Create a Some Maybe."""
    return Maybe(_value=value, _is_some=True)


def Nothing() -> Maybe[Any]:
    """Create a Nothing Maybe."""
    return Maybe(_is_some=False)


def try_op(f: Callable[[], T]) -> Result[T, Exception]:
    """Wrap operation in try/catch as Result."""
    try:
        return Success(f())
    except Exception as e:
        logger.exception("Operation failed")
        return Failure(e)


# Functional composition utilities
def pipe(value: T, *functions: Callable[[T], T]) -> T:
    """
    Left-to-right function composition.
    
    pipe(data, extract, transform, validate, save)
    """
    return reduce(lambda v, f: f(v), functions, value)


def compose(*functions: Callable[[T], T]) -> Callable[[T], T]:
    """
    Right-to-left function composition.
    
    composed = compose(save, validate, transform, extract)
    result = composed(data)
    """
    return lambda x: reduce(lambda v, f: f(v), reversed(functions), x)


def curry(f: Callable[P, T]) -> Callable[P, T]:
    """
    Simple curry wrapper (Python has limited curry support).
    Use functools.partial for most cases.
    """
    return f


def tap(f: Callable[[T], Any]) -> Callable[[T], T]:
    """
    Side effect for observation, returns original value.
    
    pipe(data, extract, tap(log_progress), transform)
    """
    def wrapper(x: T) -> T:
        f(x)
        return x
    return wrapper


def when(pred: Callable[[T], bool], f: Callable[[T], T]) -> Callable[[T], T]:
    """
    Conditional transformation.
    
    pipe(data, when(needs_processing, process))
    """
    def wrapper(x: T) -> T:
        return f(x) if pred(x) else x
    return wrapper


def unless(pred: Callable[[T], bool], f: Callable[[T], T]) -> Callable[[T], T]:
    """Conditional transformation (inverted)."""
    def wrapper(x: T) -> T:
        return x if pred(x) else f(x)
    return wrapper


# Error handling utilities
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
    step_name: str
) -> Callable[[Callable[P, T]], Callable[P, Result[T, PipelineError]]]:
    """
    Decorator to convert exceptions to Result.
    
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
                err = PipelineError(
                    step=step_name,
                    message=str(e),
                    cause=e
                )
                return Failure(err)
        return wrapper
    return decorator


# Cast helper for type narrowing
def cast(t: type[T], val: Any) -> T:
    """Runtime cast with assertion."""
    assert isinstance(val, t), f"Expected {t}, got {type(val)}"
    return val


# Lazy evaluation helpers
def lazy(f: Callable[[], T]) -> Callable[[], T]:
    """
    Lazy/deferred evaluation.
    
    expensive = lazy(lambda: compute_expensive())
    value = expensive()  # Only computed when called
    """
    cache: list[T] = []
    def wrapper() -> T:
        if not cache:
            cache.append(f())
        return cache[0]
    return wrapper


__all__ = [
    "Result", "Success", "Failure",
    "Maybe", "Some", "Nothing",
    "PipelineError",
    "try_op", "pipe", "compose", "tap", "when", "unless",
    "catch_as_result", "lazy",
]
