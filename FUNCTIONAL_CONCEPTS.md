# Functional Programming Concepts: Where They Appear in the Codebase

This document catalogs every functional programming concept used in the CMS Claims
Pipeline, with exact file locations and code examples. Each section explains the
concept, then shows where and how it is used.

---

## Table of Contents

1. [Monads (Result, Maybe)](#1-monads-result-maybe)
2. [Functors (.map)](#2-functors-map)
3. [Function Composition (pipe, compose)](#3-function-composition-pipe-compose)
4. [Higher-Order Functions](#4-higher-order-functions)
5. [Closures](#5-closures)
6. [Immutability (Frozen Dataclasses)](#6-immutability-frozen-dataclasses)
7. [Algebraic Data Types (Sum Types + Product Types)](#7-algebraic-data-types-sum-types--product-types)
8. [Pattern Matching](#8-pattern-matching)
9. [Referential Transparency (Pure Functions)](#9-referential-transparency-pure-functions)
10. [Interpreter Pattern (Free Monad-like)](#10-interpreter-pattern-free-monad-like)
11. [Lazy Evaluation](#11-lazy-evaluation)
12. [Memoisation](#12-memoisation)
13. [Fold / Reduce](#13-fold--reduce)
14. [Conditional Combinators (when / unless)](#14-conditional-combinators-when--unless)
15. [Property-Based Testing (Algebraic Laws)](#15-property-based-testing-algebraic-laws)
16. [Recursion](#16-recursion)

---

## 1. Monads (Result, Maybe)

### What is a monad?

A monad is a type that wraps a value and provides two operations:
- **`return`** (called `Success` or `Some`): wrap a plain value
- **`bind`** (called `.bind()` in Python): chain operations that might fail or be absent

The key property: `.bind()` short-circuits. If a `Result` is already a `Failure`,
`.bind(f)` skips `f` entirely and propagates the failure. This eliminates nested
`if err != nil` checks.

### Where it's used

#### Result Monad — `src/functional.py` (re-exported from `returns` library)

```python
from returns.result import Result, Success, Failure
```

**Used in `src/pipeline/receive_pure.py`** — chaining operations that can fail:

```python
# receive_step_pure() — monadic bind chains three operations:
return (
    inventory_directory(old_system_dir)          # Result[FileInventory, Exception]
    .bind(lambda inventory:                       # If Success, continue...
        Success((inventory, discover_files(old_system_dir)))
    )
    .bind(lambda pair:                            # If Success, continue...
        _create_receive_result(
            source_dir=str(old_system_dir),
            discovered=pair[1],
            inventory=pair[0],
            ...
        )
    )
)
```

If `inventory_directory` fails, the two `.bind()` calls are **skipped entirely** —
the `Failure` propagates automatically.

**Used in `src/zset.py`** — wrapping DuckDB operations:

```python
def execute_diff(con, old, new, ...) -> Result[ZSetDiffResult, Exception]:
    def _run() -> ZSetDiffResult:
        # ... execute SQL ...
        return ZSetDiffResult(view=view, stats=stats, field_deltas=tuple(deltas))
    try:
        return Success(_run())
    except Exception as e:
        return Failure(e)
```

**Used in `src/pipeline/runner_fp.py`** — every step returns `Result[PipelineState, Exception]`:

```python
def step1_functional(state: PipelineState) -> Result[PipelineState, Exception]:
    # ... do work ...
    return Success(new_state)
```

#### Maybe Monad — `src/functional.py`

```python
from returns.maybe import Maybe, Some, Nothing
```

**Used in `src/pipeline/state.py`** — optional configuration values:

```python
@dataclass(frozen=True)
class PipelineConfig:
    new_data_dir: Maybe[Path] = Nothing   # Some(path) or Nothing
    db_path: Maybe[Path] = Nothing        # Some(path) or Nothing
```

**Used in `src/pipeline/receive_pure.py`** — safe lookup:

```python
class FileInventory:
    def get(self, name: str) -> Maybe[FileInfo]:
        for f in self.files:
            if f.name == name:
                return Some(f)
        return Nothing    # Never returns None — always a typed Maybe
```

**Used in `src/pipeline/state.py`** — safe access to pipeline results:

```python
def get_last_outcome(self) -> Maybe[StepOutcome]:
    if not self.outcomes:
        return Nothing
    return Some(self.outcomes[-1])
```

### Monad laws verified

The three monad laws are tested with Hypothesis in `tests/test_property_based.py`:

```python
class TestResultMonadLaws:
    def test_left_identity(self, x):     # Success(a).bind(f) == f(a)
    def test_right_identity(self, x):    # m.bind(Success) == m
    def test_associativity(self, x):     # m.bind(f).bind(g) == m.bind(λx: f(x).bind(g))

class TestMaybeMonadLaws:
    def test_left_identity(self, x):     # Some(a).bind(f) == f(a)
    def test_right_identity(self, x):    # m.bind(Some) == m
    def test_associativity(self, x):     # m.bind(f).bind(g) == m.bind(λx: f(x).bind(g))
```

---

## 2. Functors (.map)

### What is a functor?

A functor is a type that supports `.map(f)` — applying a function to the value
inside the container without unwrapping it. If the container is empty (Failure,
Nothing), `.map()` is a no-op.

### Where it's used

**`Result.map()`** — transform a success value without handling failure:

```python
# In returns library, used throughout the codebase:
Success(42).map(lambda x: x * 2)     # → Success(84)
Failure("err").map(lambda x: x * 2)  # → Failure("err")  (f never called)
```

**`Maybe.map()`** — transform an optional value:

```python
Some(42).map(lambda x: x * 2)    # → Some(84)
Nothing.map(lambda x: x * 2)     # → Nothing  (f never called)
```

### Functor laws verified

Tested in `tests/test_property_based.py`:

```python
class TestResultFunctorLaws:
    def test_identity(self, x):       # map(id) == id
    def test_composition(self, x):    # map(f . g) == map(f) . map(g)
```

---

## 3. Function Composition (pipe, compose)

### What is function composition?

Combining simple functions into complex pipelines:
- **`pipe(x, f, g, h)`** = `h(g(f(x)))` — left-to-right (data flows forward)
- **`compose(h, g, f)`** = `lambda x: h(g(f(x)))` — right-to-left (math notation)

### Where it's used

**Defined in `src/functional.py`:**

```python
def pipe(value: T, *functions: Callable) -> T:
    """Left-to-right composition. Alias for returns.pipeline.flow."""
    return flow(value, *functions)

def compose(*functions: Callable) -> Callable:
    """Right-to-left function composition."""
    return lambda x: reduce(lambda v, f: f(v), reversed(functions), x)
```

**`compose_pipeline` in `src/pipeline/state.py`** — the most important composition
in the project. It chains all 6 pipeline steps:

```python
def compose_pipeline(*steps: StepFunction) -> Pipeline:
    """Compose multiple steps into a pipeline. Failures short-circuit."""
    def pipeline(initial_state: PipelineState) -> Result[PipelineState, Exception]:
        state = initial_state
        for step in steps:
            result = step(state)
            if is_err(result):
                return result           # ← short-circuit on failure
            state = result.unwrap()
            if state.should_halt():
                break                   # ← halt propagation
        return Success(state)
    return pipeline
```

**Called in `src/pipeline/runner_fp.py`:**

```python
pipeline = compose_pipeline(
    step1_functional,        # PipelineState → Result[PipelineState, Exception]
    step2_functional,        # PipelineState → Result[PipelineState, Exception]
    step3_functional(ctx),   # PipelineState → Result[PipelineState, Exception]
    step4_functional(ctx),   # PipelineState → Result[PipelineState, Exception]
    step5_functional(ctx),   # PipelineState → Result[PipelineState, Exception]
    step6_functional(ctx),   # PipelineState → Result[PipelineState, Exception]
)

final_result = pipeline(initial_state)  # Run the entire composed pipeline
```

### Composition laws verified

Tested in `tests/test_property_based.py`:

```python
class TestCompositionLaws:
    def test_pipe_identity(self, x):              # pipe(x) == x
    def test_compose_identity(self, x):           # compose(id)(x) == x
    def test_pipe_compose_equivalence(self, x):   # pipe(x, f, g) == compose(g, f)(x)
    def test_compose_associativity(self, x):      # compose(f, compose(g, h)) == compose(compose(f, g), h)
```

---

## 4. Higher-Order Functions

### What is a higher-order function?

A function that takes another function as a parameter, or returns a function.

### Where it's used

**`when` and `unless` in `src/functional.py`** — take a predicate function and a
transform function, return a new function:

```python
def when(pred: Callable[[T], bool], f: Callable[[T], T]) -> Callable[[T], T]:
    """Conditional transformation: apply f only if pred is true."""
    def wrapper(x: T) -> T:
        return f(x) if pred(x) else x
    return wrapper
```

**`catch_as_result` in `src/functional.py`** — a decorator (function → function):

```python
def catch_as_result(step_name: str) -> Callable:
    """Decorator: convert exceptions to Result[T, PipelineError]."""
    def decorator(f):
        def wrapper(*args, **kwargs):
            try:
                return Success(f(*args, **kwargs))
            except Exception as e:
                return Failure(PipelineError(step=step_name, message=str(e), cause=e))
        return wrapper
    return decorator
```

**`with_zip_extraction` in `src/pipeline/receive_pure.py`** — factory that returns
a function:

```python
def with_zip_extraction(directory: Path, password=None) -> Callable[[Path], Result[Path, Exception]]:
    """Higher-order function: Creates function that extracts zips if needed."""
    def processor(input_dir: Path) -> Result[Path, Exception]:
        zips = list(input_dir.glob("*.zip"))
        if not zips:
            return Success(input_dir)
        for zip_file in zips:
            result = extract_zip(zip_file, directory, password)
            if is_err(result):
                return Failure(result.failure())
        return Success(directory)
    return processor
```

**`step_wrapper` in `src/pipeline/state.py`** — wraps a step function with
halt-checking and error conversion:

```python
def step_wrapper(step_name, step_fn) -> Callable[[PipelineState], Result[PipelineState, Exception]]:
    """Higher-order function: Wraps a step for railway-oriented execution."""
    def wrapped(state):
        if state.should_halt():
            return Success(state)
        result = step_fn(state)
        if is_err(result):
            outcome = StepOutcome.err(step_name, str(result.failure()), ...)
            return Success(state.with_outcome(outcome))
        return result
    return wrapped
```

---

## 5. Closures

### What is a closure?

A function that captures variables from its enclosing scope. The inner function
"closes over" the outer variables and carries them with it.

### Where it's used

**Steps 3-6 in `src/pipeline/steps_fp.py`** — each step is a closure factory.
The outer function captures the `PipelineContext`, the inner function is the
actual step:

```python
def step3_functional(ctx: PipelineContext) -> callable:
    """Closure: returns a StepFunction that carries the ctx for DB access."""

    def _step(state: PipelineState) -> Result[PipelineState, Exception]:
        # _step closes over `ctx` from the outer scope
        con_result = _execute_ingest_plan(plan, ctx)  # ← ctx captured here
        # ...
    return _step
```

This allows the pipeline composer to work with a uniform signature
(`PipelineState → Result`) while each step secretly carries its own context:

```python
pipeline = compose_pipeline(
    step1_functional,           # No closure needed (pure)
    step2_functional,           # No closure needed (pure)
    step3_functional(ctx),      # Returns a closure carrying ctx
    step4_functional(ctx),      # Returns a closure carrying ctx
    step5_functional(ctx),      # Returns a closure carrying ctx
    step6_functional(ctx),      # Returns a closure carrying ctx
)
```

**`legacy_adapter` in `src/pipeline/runner_fp.py`** — closes over both the step
function and the context:

```python
def legacy_adapter(step_name, step_fn, ctx) -> StepFunction:
    def adapted(state):
        result = step_fn(ctx)   # ← step_fn and ctx captured from outer scope
        # ...
    return adapted
```

**`lazy` in `src/functional.py`** — closes over a mutable cache list:

```python
def lazy(f):
    cache: list[T] = []         # ← captured by wrapper
    def wrapper() -> T:
        if not cache:
            cache.append(f())   # ← mutates captured cache
        return cache[0]
    return wrapper
```

---

## 6. Immutability (Frozen Dataclasses)

### What is immutability?

Data that cannot be changed after creation. Instead of mutating an object, you
create a new one with the desired changes. This eliminates an entire class of bugs
(shared mutable state).

### Where it's used

**Every data type in the project is frozen:**

`src/pipeline/state.py` — pipeline state:
```python
@dataclass(frozen=True, slots=True)
class PipelineState:
    config: PipelineConfig
    outcomes: tuple[StepOutcome, ...] = ()
    halted: bool = False

    def with_outcome(self, outcome: StepOutcome) -> PipelineState:
        """Return a NEW state — self is never modified."""
        return replace(self, outcomes=self.outcomes + (outcome,), ...)
```

`src/zset.py` — Z-set results:
```python
@dataclass(frozen=True)
class TableRef:      # Immutable reference to a DuckDB table
@dataclass(frozen=True)
class ZSetView:      # Immutable view of a Z-set table
@dataclass(frozen=True)
class ZSetStats:     # Immutable statistics
@dataclass(frozen=True)
class FieldDelta:    # Immutable field comparison result
@dataclass(frozen=True)
class ZSetDiffResult:  # Immutable aggregate result
```

`src/pipeline/query_algebra.py` — operation descriptions:
```python
@dataclass(frozen=True)
class IngestOp:       # Immutable ingest operation
@dataclass(frozen=True)
class IngestPlan:     # Immutable ingest plan
@dataclass(frozen=True)
class AnomalyCheck:   # Immutable anomaly check description
@dataclass(frozen=True)
class MatchConfig:    # Immutable match configuration
@dataclass(frozen=True)
class ExportOp:       # Immutable export operation
@dataclass(frozen=True)
class ReportPlan:     # Immutable report plan
```

`src/pipeline/receive_pure.py` — file metadata:
```python
@dataclass(frozen=True)
class FileInfo:          # Immutable file metadata
@dataclass(frozen=True)
class FileInventory:     # Immutable inventory
@dataclass(frozen=True)
class DiscoveredFiles:   # Immutable discovery result
@dataclass(frozen=True)
class ReceiveResult:     # Immutable step result
```

**Why tuples instead of lists?** Tuples are immutable in Python. Every collection
in the frozen dataclasses uses `tuple[...]` not `list[...]`:

```python
outcomes: tuple[StepOutcome, ...] = ()     # Not list[StepOutcome]
operations: tuple[IngestOp, ...] = ()      # Not list[IngestOp]
files: tuple[FileInfo, ...] = ()           # Not list[FileInfo]
```

---

## 7. Algebraic Data Types (Sum Types + Product Types)

### What are algebraic data types?

- **Product types**: types that combine multiple fields (structs/dataclasses).
  `FileInfo` has name AND path AND size AND sha256.
- **Sum types**: types that are one of several variants. `Result` is `Success(value)`
  OR `Failure(error)`. `Maybe` is `Some(value)` OR `Nothing`.

### Where it's used

**Sum types (discriminated unions):**

```python
# Result = Success(T) | Failure(E)
result: Result[int, str] = Success(42)   # one variant
result: Result[int, str] = Failure("err")  # the other

# Maybe = Some(T) | Nothing
maybe: Maybe[int] = Some(42)
maybe: Maybe[int] = Nothing
```

**Product types (records):**

```python
# Every frozen dataclass is a product type
@dataclass(frozen=True)
class StepOutcome:
    step_name: str       # AND
    success: bool        # AND
    message: str         # AND
    errors: tuple[str, ...]  # AND
    warnings: tuple[str, ...]
```

**`FileType` in `src/pipeline/schema_validate_pure.py`** acts as a discriminated
union via its `kind` field:

```python
@dataclass(frozen=True)
class FileType:
    kind: str  # "beneficiary" | "carrier_claims" | "unknown"
```

This is used with pattern matching as a poor man's algebraic data type (see
section 8).

---

## 8. Pattern Matching

### What is pattern matching?

Structural destructuring on data types — like a `switch` statement that can
also extract values from the matched structure. Python 3.10+ supports this
via `match`/`case`.

### Where it's used

**`src/pattern_matching.py`** — dedicated showcase module:

```python
# Destructuring Result
def describe_result(result: Result[T, E]) -> str:
    match result:
        case Success(value):           # Extract the inner value
            return f"Success: {value}"
        case Failure(error):           # Extract the inner error
            return f"Failure: {error}"

# Nested destructuring with guards
def handle_pipeline_error(result):
    match result:
        case Failure(PipelineError(step="receive", message=msg)):
            return f"Receive failed: {msg}"
        case Failure(PipelineError(step=step, message=msg, cause=cause)) if cause is not None:
            return f"[{step}] {msg} (caused by {type(cause).__name__})"

# Destructuring Maybe
def maybe_to_str(maybe, default="<empty>"):
    match maybe:
        case Some(value):
            return str(value)
        case nothing if is_nothing(nothing):
            return default

# Tuple pattern matching with guards
class Threshold:
    def check(self, count):
        match (count >= self.min_files, count >= self.warn_below):
            case (True, True):   return "OK"
            case (True, False):  return "WARNING"
            case (False, _):     return "FAIL"
```

**`src/pipeline/runner_fp.py`** — matching on Maybe for optional config:

```python
# In step1_functional:
match state.config.new_data_dir:
    case Some(new_dir):
        new_result = receive_new_system_pure(new_dir)
        # ...
    case _:
        pass

# In step2_functional:
match state.config.new_data_dir:
    case Some(new_dir):
        new_system_dir = new_dir
    case _:
        new_system_dir = None
```

**`src/pipeline/steps_fp.py`** — matching on Maybe for new system detection:

```python
# In _build_ingest_plan:
match config.new_data_dir:
    case Some(new_dir):
        for path in sorted(new_dir.glob("*Beneficiary*.csv")):
            ops.append(IngestOp(...))
    case _:
        pass
```

### Tests

28 tests in `tests/test_pattern_matching.py` verify all pattern matching functions.

---

## 9. Referential Transparency (Pure Functions)

### What is referential transparency?

A function is pure (referentially transparent) if:
1. Same inputs always produce the same output
2. No side effects (no I/O, no mutation, no database calls)

You can replace `f(x)` with its result anywhere in the program without changing
behavior.

### Where it's used

**`src/pipeline/receive_pure.py`** — pure file operations:

```python
def discover_files(directory: Path) -> DiscoveredFiles:
    """Pure function: Discover CSV files by category. No side effects."""
    beneficiary = tuple(f.name for f in directory.glob("*Beneficiary*") if f.suffix == ".csv")
    carrier = tuple(f.name for f in directory.glob("*Carrier*") if f.suffix == ".csv")
    return DiscoveredFiles(beneficiary=tuple(sorted(beneficiary)), carrier_claims=tuple(sorted(carrier)))

def validate_discovery(discovered, expected_beneficiary=3, expected_carrier=2):
    """Pure validation: same inputs → same output, always."""
    missing = []
    if len(discovered.beneficiary) < expected_beneficiary:
        missing.append(...)
    return len(missing) == 0, tuple(missing)
```

**`src/zset.py`** — pure SQL generators (Layer 1):

```python
def diff_sql(old: TableRef, new: TableRef, result_table: str) -> str:
    """Pure: same TableRefs always produce the same SQL string."""
    # No database access — returns a string

def stats_sql(result_table: str) -> str:
    """Pure: table name → SQL string."""

def field_diff_sql(old, new, columns, is_numeric=False) -> str:
    """Pure: refs + columns → SQL string."""
```

**`src/pipeline/query_algebra.py`** — pure data descriptions:

```python
# ANOMALY_CHECKS is a tuple of frozen dataclasses — pure data, no behavior
ANOMALY_CHECKS: tuple[AnomalyCheck, ...] = (
    AnomalyCheck(name="null_bene_id", table="beneficiary_summary",
                 query="SELECT COUNT(*) FROM beneficiary_summary WHERE DESYNPUF_ID IS NULL",
                 threshold=0, severity="high"),
    # ...
)
```

---

## 10. Interpreter Pattern (Free Monad-like)

### What is the interpreter pattern?

Separate **what** to do (a pure description) from **how** to do it (effectful
execution). In Haskell this is the "free monad" pattern. In our project:

- **Pure layer**: frozen dataclasses describing operations (the "what")
- **Interpreter**: a single function that executes them (the "how")

### Where it's used

**Step 3 (Ingest):**

```python
# Pure: build a plan (src/pipeline/steps_fp.py)
plan = _build_ingest_plan(state.config)
# plan is an IngestPlan(operations=(...), skip_ingest=False)
# It describes what to ingest but does NOT touch DuckDB

# Effectful: execute the plan
con_result = _execute_ingest_plan(plan, ctx)
# This is the ONLY function that calls con.execute()
```

**Step 4 (Z-set matching):**

```python
# Pure: build table references
old_ref = TableRef(name=cfg.old_table, key_cols=cfg.key_cols)
new_ref = TableRef(name=cfg.new_table, key_cols=cfg.key_cols)

# Pure: generate SQL (inside execute_diff)
sql = diff_sql(old_ref, new_ref, result_table)   # returns a string

# Effectful: execute the SQL
con.execute(sql)  # single boundary
```

**Step 6 (Report/Export):**

```python
# Pure: build export plan
plan = _build_export_plan(con, report_dir)
# plan is a ReportPlan(export_ops=(...))

# Effectful: execute the plan
csv_exports, parquet_exports, warnings = _execute_export_plan(con, plan)
```

**Anomaly checks (`src/pipeline/query_algebra.py` + `steps_fp.py`):**

```python
# Pure: anomaly checks as data
ANOMALY_CHECKS = (
    AnomalyCheck(name="null_bene_id", query="SELECT COUNT(*)...", threshold=0),
    AnomalyCheck(name="future_birth", query="SELECT COUNT(*)...", threshold=0),
    # ...
)

# Effectful: interpreter runs each check
def _execute_anomaly_checks(con, checks):
    results = []
    for check in checks:
        row = con.execute(check.query).fetchone()  # single boundary
        results.append(AnomalyResult(check=check, count=row[0]))
    return tuple(results)
```

---

## 11. Lazy Evaluation

### What is lazy evaluation?

Deferring computation until the result is actually needed. The computation is
described but not executed immediately.

### Where it's used

**`lazy` in `src/functional.py`:**

```python
def lazy(f: Callable[[], T]) -> Callable[[], T]:
    """Deferred evaluation with memoisation."""
    cache: list[T] = []
    def wrapper() -> T:
        if not cache:
            cache.append(f())   # Only computed on first call
        return cache[0]
    return wrapper

# Usage:
expensive = lazy(lambda: compute_expensive_thing())
# compute_expensive_thing() has NOT run yet
value = expensive()  # NOW it runs
value = expensive()  # Returns cached result — no recomputation
```

**The interpreter pattern itself is a form of laziness** — the `IngestPlan`,
`ReportPlan`, and `AnomalyCheck` dataclasses describe computations without
executing them. Execution is deferred until the interpreter is called.

---

## 12. Memoisation

### What is memoisation?

Caching the result of a function so it's only computed once. A specific form of
lazy evaluation.

### Where it's used

**`lazy` in `src/functional.py`** doubles as a memoiser:

```python
def lazy(f):
    cache: list[T] = []
    def wrapper() -> T:
        if not cache:
            cache.append(f())
        return cache[0]    # Always returns the cached result after first call
    return wrapper
```

**Verified in `tests/test_property_based.py`:**

```python
def test_lazy_memoisation(self, x):
    """lazy(f) calls f at most once regardless of access count."""
    call_count = 0
    def f():
        nonlocal call_count
        call_count += 1
        return x
    memo = lazy(f)
    _ = memo()
    _ = memo()
    _ = memo()
    assert call_count == 1    # f was only called once
```

---

## 13. Fold / Reduce

### What is a fold?

Processing a collection by accumulating a result one element at a time. In
functional programming, this replaces loops.

### Where it's used

**`compose` in `src/functional.py`** — built on `reduce`:

```python
def compose(*functions):
    return lambda x: reduce(lambda v, f: f(v), reversed(functions), x)
```

**`compose_pipeline` in `src/pipeline/state.py`** — folds over steps:

```python
def compose_pipeline(*steps):
    def pipeline(initial_state):
        state = initial_state
        for step in steps:          # This is a fold:
            result = step(state)    #   accumulator = state
            state = result.unwrap() #   each step transforms it
        return Success(state)       # Final accumulated value
    return pipeline
```

**Step 6 in `src/pipeline/steps_fp.py`** — described in the code as a "pure fold":

```python
# 1. Pure fold: gather all data for the report
profiles = ctx.results.get("profiles", {})
validations = ctx.results.get("validations", [])
comparisons = ctx.results.get("comparisons", [])
# These accumulated results from Steps 3-5 are "folded" into the report
```

**Accumulation via `with_outcome`** — the pipeline state is built by repeatedly
folding outcomes into it:

```python
state = state.with_outcome(outcome1)  # fold step 1 result
state = state.with_outcome(outcome2)  # fold step 2 result
# ... each call returns a NEW immutable state
```

---

## 14. Conditional Combinators (when / unless)

### What are conditional combinators?

Functions that conditionally apply a transformation based on a predicate, without
using `if`/`else` statements. They compose naturally with `pipe`.

### Where they're defined

**`src/functional.py`:**

```python
def when(pred, f):
    """Apply f only if pred is true. Otherwise return x unchanged."""
    def wrapper(x):
        return f(x) if pred(x) else x
    return wrapper

def unless(pred, f):
    """Apply f only if pred is false. Otherwise return x unchanged."""
    def wrapper(x):
        return x if pred(x) else f(x)
    return wrapper
```

### Properties verified

**`tests/test_property_based.py`:**

```python
class TestConditionalCombinators:
    def test_when_unless_inverse(self, x):
        """when(p, f) and unless(p, f) cover all cases exactly once."""
        # If x > 0: when applies f, unless returns identity
        # If x <= 0: when returns identity, unless applies f

    def test_when_false_is_identity(self, x):
        """when(False, f)(x) == x"""

    def test_unless_true_is_identity(self, x):
        """unless(True, f)(x) == x"""
```

---

## 15. Property-Based Testing (Algebraic Laws)

### What is property-based testing?

Instead of writing specific test cases (`assert f(3) == 9`), you specify
*properties* that must hold for all inputs (`∀x: f(x) >= 0`). The testing
framework (Hypothesis) generates hundreds of random inputs to try to find
a counterexample.

### Where it's used

**`tests/test_property_based.py`** — 31 tests verifying algebraic laws:

```python
# Monad laws (3 per monad × 2 monads = 6, plus short-circuit tests)
class TestResultMonadLaws:    # Left identity, right identity, associativity
class TestMaybeMonadLaws:     # Left identity, right identity, associativity

# Functor laws (2 for Result + 1 failure case)
class TestResultFunctorLaws:  # Identity, composition

# Composition laws (4 properties)
class TestCompositionLaws:    # Identity, equivalence, associativity

# Combinator laws (3 properties)
class TestConditionalCombinators:  # Inverse, identity cases

# Domain invariants (8+ properties)
class TestFileInventoryProperties:    # Lookup correctness, serialization
class TestDiscoverFilesProperties:    # Union property, validation completeness
class TestClassifyFileProperties:     # Schema classification correctness
class TestColumnDiffProperties:       # Superset has no missing columns

# Effect boundary (3 properties)
class TestTryOpProperties:    # Pure succeeds, throwing fails, lazy memoises
```

**`tests/test_zset.py`** — algebraic properties of Z-sets:

```python
class TestZSetAlgebraicProperties:
    def test_identity_diff_is_empty(self):           # A - A = {}
    def test_empty_new_is_all_deletions(self):       # A - {} = all deletions
    def test_empty_old_is_all_insertions(self):      # {} - A = all insertions
    def test_stats_sum_to_total(self):               # ins + del + unch == total
    def test_net_change_is_insertions_minus_deletions(self):  # net = ins - del
```

---

## 16. Recursion

### What is recursion?

A function that calls itself to solve a problem by breaking it into smaller
sub-problems.

### Honest assessment: We don't use explicit recursion

This pipeline processes data with DuckDB SQL (set-based, not recursive) and
Python loops. There is no recursive function in the codebase.

This is intentional — recursion in Python has two practical problems:
1. Python has a call stack limit (default 1,000 frames, no tail-call optimization)
2. DuckDB's columnar engine is far more efficient for set operations than
   Python-level recursion over rows

The **functional alternatives to recursion** that we do use:
- **`reduce`** (in `compose`) — replaces recursive folding
- **`for` loops over immutable data** — each iteration produces a new value,
  no mutation of existing data
- **SQL set operations** — `FULL OUTER JOIN`, `GROUP BY`, `SUM` replace what
  might be recursive traversals in other contexts

If we needed recursion (e.g., tree-structured data), we would use `reduce` or
trampolining to stay within Python's stack limits.

---

## Summary Table

| Concept | Files | Primary Use |
|---------|-------|-------------|
| **Result monad** | `functional.py`, `receive_pure.py`, `zset.py`, `runner_fp.py`, `steps_fp.py` | Error handling without exceptions |
| **Maybe monad** | `functional.py`, `state.py`, `receive_pure.py` | Optional values without None |
| **Functor (.map)** | `functional.py` (via `returns`) | Transform wrapped values |
| **Function composition** | `functional.py`, `state.py`, `runner_fp.py` | Pipeline construction |
| **Higher-order functions** | `functional.py`, `receive_pure.py`, `state.py` | Abstraction, decoration |
| **Closures** | `steps_fp.py`, `runner_fp.py`, `functional.py` | Carrying context through pipeline |
| **Immutability** | `state.py`, `zset.py`, `query_algebra.py`, `receive_pure.py` | All data types are frozen |
| **Algebraic data types** | `functional.py` (via `returns`), `schema_validate_pure.py` | Sum types (Result, Maybe) + product types |
| **Pattern matching** | `pattern_matching.py`, `runner_fp.py`, `steps_fp.py` | Structural destructuring |
| **Pure functions** | `zset.py` (Layer 1), `receive_pure.py`, `query_algebra.py` | Testable, predictable logic |
| **Interpreter pattern** | `zset.py`, `steps_fp.py`, `query_algebra.py` | Separate description from execution |
| **Lazy evaluation** | `functional.py` | Deferred computation |
| **Memoisation** | `functional.py` | Cache expensive results |
| **Fold / reduce** | `functional.py`, `state.py`, `steps_fp.py` | Accumulate results |
| **Conditional combinators** | `functional.py` | Composable conditionals |
| **Property-based testing** | `test_property_based.py`, `test_zset.py` | Verify algebraic laws |
| **Recursion** | *(not used)* | Replaced by reduce, SQL, iteration over immutable data |
