# Functional Programming Concepts: Where They Appear in the Codebase

This document catalogs every functional programming concept used in the CMS Claims
Pipeline, with exact file locations and code examples. Each section explains the
concept, then shows where and how it is used.

---

## Table of Contents

### Core Concepts
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

### Design Patterns
17. [Railway-Oriented Programming](#17-railway-oriented-programming)
18. [Functional Core, Imperative Shell](#18-functional-core-imperative-shell)
19. [Smart Constructors](#19-smart-constructors)
20. [Newtype / Semantic Wrapper](#20-newtype--semantic-wrapper)

### Future Extensions
21. [Where We'd Go Next](#21-where-wed-go-next)

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

### Current status: Not used (deliberately)

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

### Future use case: Recursive ICD Code Hierarchy Validation

CMS claims data includes ICD diagnosis codes (e.g., `E11.65` — Type 2 diabetes
with hyperglycemia). These codes form a **tree**:

```
ICD-10 Root
├── E00-E89: Endocrine, nutritional, metabolic
│   ├── E10: Type 1 diabetes
│   │   ├── E10.1: with ketoacidosis
│   │   ├── E10.2: with kidney complications
│   │   │   ├── E10.21: with diabetic nephropathy
│   │   │   └── E10.22: with diabetic CKD
│   │   └── E10.6: with other specified complications
│   └── E11: Type 2 diabetes
│       ├── E11.6: with other specified complications
│       │   └── E11.65: with hyperglycemia
│       └── ...
└── ...
```

If we needed to validate that every diagnosis code on a claim is consistent with
its parent category (e.g., a claim for `E11.65` should also have the patient
flagged for `SP_DIABETES`), we'd need to **walk up the tree** from each code.

A recursive catamorphism (tree fold) would be the natural solution:

```python
@dataclass(frozen=True)
class ICDNode:
    code: str
    description: str
    children: tuple['ICDNode', ...]  # Recursive structure

def catamorphism(node: ICDNode, f: Callable) -> T:
    """
    Recursive fold over a tree — the functional way to process
    hierarchical data without mutation.

    f receives the node and the already-folded results of its children.
    """
    child_results = tuple(catamorphism(child, f) for child in node.children)
    return f(node, child_results)

# Example: count all codes under a category
def count_codes(node: ICDNode, child_counts: tuple[int, ...]) -> int:
    return 1 + sum(child_counts)

# Example: find all leaf codes (no children)
def collect_leaves(node: ICDNode, child_leaves: tuple[list, ...]) -> list:
    if not node.children:
        return [node.code]
    return [code for leaves in child_leaves for code in leaves]

# Example: validate a claim's codes against the hierarchy
def validate_claim_codes(
    claim_codes: frozenset[str],
    hierarchy: ICDNode,
) -> Result[frozenset[str], list[str]]:
    """
    Recursively walk the ICD tree. For each code in the claim,
    verify its ancestors are consistent with the patient's flags.
    """
    def check(node, child_results):
        errors = [e for results in child_results for e in results]
        if node.code in claim_codes:
            # Check parent consistency...
            pass
        return errors

    errors = catamorphism(hierarchy, check)
    return Success(claim_codes) if not errors else Failure(errors)
```

To handle Python's stack limit for deep trees, we'd use **trampolining**:

```python
from typing import Generator

def trampoline(f: Generator):
    """
    Trampoline: convert recursive calls into a flat loop.
    Each 'yield' is a suspended recursive call; the trampoline
    resumes it iteratively, avoiding stack overflow.
    """
    result = next(f)
    stack = [f]
    while stack:
        try:
            result = stack[-1].send(result)
            if hasattr(result, '__next__'):
                stack.append(result)
                result = next(result)
        except StopIteration as e:
            stack.pop()
            result = e.value
    return result
```

This is not a stretch — CMS data **does** contain ICD codes, and hierarchical
validation is a real need for claims data quality. The current pipeline validates
flat fields; extending to tree-structured medical codes is a natural next step.

---

## 17. Railway-Oriented Programming

### What is it?

A design pattern (coined by Scott Wlaschin) where data flows along two "tracks":

```
Success track:  ──[Step 1]──→──[Step 2]──→──[Step 3]──→── ✓ Final result
                     │              │              │
Failure track:  ─────╳──────→──────╳──────→──────╳──→── ✗ First error
```

If any step fails, all subsequent steps are **automatically skipped** — the failure
propagates along the bottom track. No explicit error checking between steps.

This is implemented via the `Result` monad's `.bind()` method: `Failure.bind(f)`
returns `Failure` without calling `f`.

### Where it's used

**The entire pipeline architecture** is railway-oriented.

**`compose_pipeline` in `src/pipeline/state.py`** — the railway switchyard:

```python
def compose_pipeline(*steps: StepFunction) -> Pipeline:
    def pipeline(initial_state: PipelineState) -> Result[PipelineState, Exception]:
        state = initial_state
        for step in steps:
            result = step(state)        # Run the step
            if is_err(result):
                return result           # ← SWITCH TO FAILURE TRACK
            state = result.unwrap()     # ← STAY ON SUCCESS TRACK
            if state.should_halt():
                break
        return Success(state)
    return pipeline
```

**`receive_step_pure` in `src/pipeline/receive_pure.py`** — railway within a step:

```python
return (
    inventory_directory(old_system_dir)       # Step A: might fail
    .bind(lambda inventory:                    # Step B: skipped if A failed
        Success((inventory, discover_files(old_system_dir)))
    )
    .bind(lambda pair:                         # Step C: skipped if A or B failed
        _create_receive_result(...)
    )
)
```

**`step_wrapper` in `src/pipeline/state.py`** — wraps any step into the railway:

```python
def step_wrapper(step_name, step_fn):
    def wrapped(state):
        if state.should_halt():        # Already on failure track
            return Success(state)      # Pass through without running
        result = step_fn(state)
        if is_err(result):
            outcome = StepOutcome.err(...)
            return Success(state.with_outcome(outcome))  # Record failure, continue
        return result
    return wrapped
```

### Why it matters

Without railway-oriented programming, the pipeline would look like:

```python
# Imperative error handling (what we replaced)
result1 = step1(ctx)
if not result1.success:
    log_error(result1)
    return result1
result2 = step2(ctx)
if not result2.success:
    log_error(result2)
    return result2
result3 = step3(ctx)
if not result3.success:
    ...  # 6 levels of nesting
```

With the railway pattern, it's:

```python
# Railway-oriented (what we have)
pipeline = compose_pipeline(step1, step2, step3, step4, step5, step6)
final = pipeline(initial_state)  # Failures automatically propagate
```

---

## 18. Functional Core, Imperative Shell

### What is it?

An architecture pattern (from Gary Bernhardt's "Boundaries" talk) where:

- **Functional core**: Pure functions and immutable data — all business logic
- **Imperative shell**: Thin layer at the edges that handles I/O, databases, files

The core is easy to test (no mocks needed). The shell is thin enough that it
barely needs testing.

### Where it's used

**This is the overall architecture of the refactored pipeline.**

```
┌─────────────────────────────────────────────────────────────┐
│                     IMPERATIVE SHELL                         │
│  runner_fp.py  — reads config, writes logs, manages DB conn  │
│  steps_fp.py   — calls con.execute() at the boundary         │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                   FUNCTIONAL CORE                        │ │
│  │                                                          │ │
│  │  state.py         — PipelineState, compose_pipeline      │ │
│  │  query_algebra.py — IngestPlan, AnomalyCheck, MatchConfig│ │
│  │  zset.py Layer 1  — diff_sql, stats_sql, field_diff_sql  │ │
│  │  receive_pure.py  — discover_files, validate_discovery   │ │
│  │  functional.py    — Result, Maybe, pipe, compose         │ │
│  │  pattern_matching.py — structural match on domain types  │ │
│  │                                                          │ │
│  │  No I/O. No database. No side effects. Pure functions.   │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  zset.py Layer 2  — execute_diff() calls con.execute()       │
│  steps_fp.py      — _execute_ingest_plan(), _execute_export  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Concrete example — Step 3 Ingest:**

```python
# CORE (pure): Build a plan — no database access
plan = _build_ingest_plan(state.config)
# plan is an IngestPlan(operations=(...), skip_ingest=False)

# SHELL (effectful): Execute it — database access happens here only
con_result = _execute_ingest_plan(plan, ctx)
```

**Concrete example — Z-set diff:**

```python
# CORE: Generate SQL string (pure, testable without DB)
sql = diff_sql(old_ref, new_ref, "_zset_beneficiary")

# SHELL: Execute it (effectful, requires DB connection)
con.execute(sql)
```

### Why it matters

The functional core can be tested with simple unit tests — no database, no
filesystem, no mocks:

```python
def test_diff_sql_contains_full_outer_join(self, old_ref, new_ref):
    sql = diff_sql(old_ref, new_ref, "_zset_test")  # No DB needed
    assert "FULL OUTER JOIN" in sql
```

The imperative shell is tested with integration tests against a small in-memory
DuckDB — but there's very little logic to test, since the shell just calls the
core and executes the result.

---

## 19. Smart Constructors

### What is a smart constructor?

A class method that validates inputs and returns a well-formed instance, instead
of letting callers construct invalid objects directly. This is the Python
equivalent of Haskell's `mkFoo :: ... -> Maybe Foo`.

### Where it's used

**`StepOutcome.ok()` and `StepOutcome.err()` in `src/pipeline/state.py`:**

```python
@dataclass(frozen=True)
class StepOutcome:
    step_name: str
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def ok(cls, step_name, message, data=None) -> StepOutcome:
        """Smart constructor: guarantees success=True, no errors."""
        return cls(step_name=step_name, success=True, message=message, data=data or {})

    @classmethod
    def err(cls, step_name, message, errors, warnings=()) -> StepOutcome:
        """Smart constructor: guarantees success=False, has errors."""
        return cls(step_name=step_name, success=False, message=message,
                   errors=errors, warnings=warnings)
```

You can't accidentally create a `StepOutcome(success=True, errors=("oops",))`
when using the smart constructors — `ok()` always has empty errors, `err()` always
has `success=False`.

**`AnomalyResult.is_anomalous` in `src/pipeline/query_algebra.py`:**

```python
@dataclass(frozen=True)
class AnomalyResult:
    check: AnomalyCheck
    count: int

    @property
    def is_anomalous(self) -> bool:
        return self.count > self.check.threshold
```

The "is this an anomaly?" logic lives on the type itself, not scattered across
the codebase. This is a weaker form of smart constructor — it doesn't prevent
construction, but it centralizes the invariant.

---

## 20. Newtype / Semantic Wrapper

### What is it?

Wrapping a primitive value in a named type to give it meaning and prevent mixing
up different things that happen to have the same underlying type. In Haskell:
`newtype UserId = UserId String`.

### Where it's used

**`TableRef` in `src/zset.py`** — wraps a table name + key columns:

```python
@dataclass(frozen=True)
class TableRef:
    name: str
    key_cols: tuple[str, ...]
```

Without `TableRef`, the Z-set functions would take `(str, tuple[str, ...])` pairs
that could easily be confused. With it, the API is self-documenting:

```python
# Clear: two named references
old = TableRef(name="beneficiary_summary", key_cols=("DESYNPUF_ID", "summary_year"))
new = TableRef(name="new_beneficiary_summary", key_cols=("DESYNPUF_ID", "summary_year"))
result = execute_diff(con, old, new, "_zset_beneficiary")

# Unclear (what we'd have without the newtype):
result = execute_diff(con, "beneficiary_summary", ("DESYNPUF_ID", "summary_year"),
                      "new_beneficiary_summary", ("DESYNPUF_ID", "summary_year"), ...)
```

**`FileType` in `src/pipeline/schema_validate_pure.py`** — wraps a string kind:

```python
@dataclass(frozen=True)
class FileType:
    kind: str  # "beneficiary" | "carrier_claims" | "unknown"
```

Instead of passing raw strings like `"beneficiary"` through the system (which
could be misspelled), we pass `FileType(kind="beneficiary")` — a typed wrapper
that can be pattern-matched.

**`PipelineError` in `src/functional.py`** — wraps error context:

```python
@dataclass(frozen=True)
class PipelineError:
    step: str
    message: str
    cause: Exception | None = None
    context: dict[str, Any] = field(default_factory=dict)
```

Instead of `Failure("something went wrong")`, we have
`Failure(PipelineError(step="ingest", message="...", cause=exc))` — structured,
pattern-matchable errors.

---

## 21. Where We'd Go Next

These are concrete extensions that a functional programming advocate would
recognize as natural evolutions of the current architecture.

### Optics (Lenses) — for deeply nested immutable updates

**Problem**: Updating a deeply nested field in an immutable structure requires
reconstructing every layer:

```python
# Current: manual reconstruction
new_state = replace(state,
    outcomes=state.outcomes + (outcome,),
    halted=True,
    halt_reason=outcome.message,
)
```

**With lenses** (e.g., `python-lenses` library):

```python
from lenses import lens

# Lens: a composable "path" into a data structure
halt_lens = lens.halted
reason_lens = lens.halt_reason
outcome_lens = lens.outcomes

# Compose lenses, then apply
update = halt_lens.set(True) & reason_lens.set(msg) & outcome_lens.modify(lambda o: o + (outcome,))
new_state = update(state)
```

This becomes valuable when `PipelineState` grows more typed result fields
(e.g., `schema_result`, `ingest_result`, `match_result` — currently commented
out in `state.py`). Lenses compose cleanly where manual `replace()` chains
become unwieldy.

### Free Monad — full DSL for pipeline operations

**Problem**: Our interpreter pattern uses frozen dataclasses (`IngestPlan`,
`AnomalyCheck`, `ExportOp`) as the "language" of operations. But each step
has its own ad-hoc set of descriptions.

**With a free monad**, all operations across all steps would share a single
algebraic language:

```python
@dataclass(frozen=True)
class PipelineOp:
    """Base class for all pipeline operations."""
    pass

@dataclass(frozen=True)
class ReadCSV(PipelineOp):
    path: Path
    target_table: str

@dataclass(frozen=True)
class ExecuteSQL(PipelineOp):
    sql: str

@dataclass(frozen=True)
class ExportTable(PipelineOp):
    table: str
    format: str  # "csv" | "parquet"
    path: Path

# A pipeline is a sequence of operations — pure data, no effects
Pipeline = tuple[PipelineOp, ...]

# One interpreter for DuckDB
def duckdb_interpreter(con, ops: Pipeline):
    for op in ops:
        match op:
            case ReadCSV(path, table):
                con.execute(f"CREATE TABLE {table} AS SELECT * FROM read_csv_auto('{path}')")
            case ExecuteSQL(sql):
                con.execute(sql)
            case ExportTable(table, "csv", path):
                con.execute(f"COPY {table} TO '{path}' (HEADER)")

# A DIFFERENT interpreter for testing (no database at all)
def mock_interpreter(ops: Pipeline) -> list[str]:
    return [f"Would execute: {op}" for op in ops]
```

The key insight: you could swap the DuckDB interpreter for a Spark interpreter,
a Snowflake interpreter, or a dry-run interpreter — the pipeline description
stays the same.

### Comonads — for windowed time-series analysis

**Problem**: Claims data has temporal structure. Analyzing trends requires looking
at surrounding context (previous year, next year) for each data point.

A **comonad** is the dual of a monad — instead of wrapping a value to add effects,
it wraps a value with its *context*. The key operation is `extend`: apply a
function that can see the whole neighborhood.

```python
@dataclass(frozen=True)
class Windowed(Generic[T]):
    """A value with its temporal context — a comonadic structure."""
    before: tuple[T, ...]   # Previous time periods
    focus: T                 # Current time period
    after: tuple[T, ...]    # Future time periods

    def extract(self) -> T:
        """Comonad extract: get the focused value."""
        return self.focus

    def extend(self, f: Callable[['Windowed[T]'], U]) -> 'Windowed[U]':
        """Comonad extend: apply f at every position with full context."""
        # f can see the entire window, not just the current value
        results = []
        for i in range(len(self.before) + 1 + len(self.after)):
            shifted = self._shift_to(i)
            results.append(f(shifted))
        return Windowed(
            before=tuple(results[:len(self.before)]),
            focus=results[len(self.before)],
            after=tuple(results[len(self.before)+1:]),
        )

# Usage: detect year-over-year anomalies in Medicare reimbursement
def detect_yoy_anomaly(window: Windowed[YearlyStats]) -> AnomalyFlag:
    current = window.focus.total_reimbursement
    if window.before:
        prev = window.before[-1].total_reimbursement
        pct_change = (current - prev) / max(prev, 1)
        if abs(pct_change) > 0.5:  # >50% change year-over-year
            return AnomalyFlag(year=window.focus.year, change_pct=pct_change)
    return AnomalyFlag(year=window.focus.year, change_pct=0.0)
```

This is relevant because the pipeline already detects financial divergences
per year (2008, 2009, 2010). A comonadic approach would let us express
"compare each year to its neighbors" as a composable, pure operation.

### Recursive Z-Set Diff on Hierarchical Claims

**Problem**: Claims have structure — a claim contains line items, each line item
has diagnosis codes, and diagnosis codes form a hierarchy (see Section 16).

Currently our Z-set diff operates on flat tables. A **recursive Z-set** would
diff at each level of the hierarchy:

```python
@dataclass(frozen=True)
class HierarchicalDiff:
    """Z-set diff at one level, with recursive child diffs."""
    level: str               # "claim" | "line_item" | "diagnosis"
    stats: ZSetStats         # Insertions/deletions/unchanged at THIS level
    field_deltas: tuple[FieldDelta, ...]
    children: tuple['HierarchicalDiff', ...]  # Recursive: diffs at child levels

def recursive_diff(
    old: TableRef, new: TableRef, con, children: list[ChildSpec]
) -> HierarchicalDiff:
    """Recursively diff a hierarchy of tables."""
    # Diff at this level
    result = execute_diff(con, old, new, f"_zset_{old.name}")
    zr = result.unwrap()

    # Recursively diff children (only for matched records)
    child_diffs = []
    for child in children:
        child_diff = recursive_diff(child.old, child.new, con, child.children)
        child_diffs.append(child_diff)

    return HierarchicalDiff(
        level=old.name,
        stats=zr.stats,
        field_deltas=zr.field_deltas,
        children=tuple(child_diffs),
    )

# Usage:
full_diff = recursive_diff(
    old=TableRef("carrier_claims", ("CLM_ID",)),
    new=TableRef("new_carrier_claims", ("CLM_ID",)),
    con=con,
    children=[
        ChildSpec(
            old=TableRef("claim_lines", ("CLM_ID", "LINE_NUM")),
            new=TableRef("new_claim_lines", ("CLM_ID", "LINE_NUM")),
            children=[
                ChildSpec(
                    old=TableRef("diagnoses", ("CLM_ID", "LINE_NUM", "ICD_CODE")),
                    new=TableRef("new_diagnoses", ("CLM_ID", "LINE_NUM", "ICD_CODE")),
                    children=[],
                )
            ],
        )
    ],
)
```

This would answer questions like: "For claims that matched, did their line items
change? For line items that matched, did their diagnosis codes change?" — drilling
down through each level of the hierarchy recursively.

---

## Summary Table

### Core Concepts

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
| **Recursion** | *(future: ICD hierarchy)* | Catamorphism over tree-structured medical codes |

### Design Patterns

| Pattern | Files | Primary Use |
|---------|-------|-------------|
| **Railway-oriented programming** | `state.py` (`compose_pipeline`), `receive_pure.py` (`.bind()` chains) | Automatic error propagation |
| **Functional core / imperative shell** | Core: `state.py`, `query_algebra.py`, `zset.py` L1; Shell: `steps_fp.py`, `zset.py` L2 | Testable core, thin I/O boundary |
| **Smart constructors** | `state.py` (`StepOutcome.ok`, `.err`) | Prevent invalid state construction |
| **Newtype / semantic wrapper** | `zset.py` (`TableRef`), `schema_validate_pure.py` (`FileType`), `functional.py` (`PipelineError`) | Type safety, self-documenting APIs |

### Future Extensions

| Concept | Applicable To | What It Would Enable |
|---------|--------------|---------------------|
| **Optics (lenses)** | `PipelineState` nested updates | Composable immutable state updates without boilerplate |
| **Free monad** | Steps 3-6 operation descriptions | Swappable interpreters (DuckDB → Spark → dry-run) |
| **Comonads** | Year-over-year trend analysis | Windowed context for temporal anomaly detection |
| **Recursive Z-set diff** | Claim → line item → diagnosis hierarchy | Multi-level structural diffing with catamorphisms |
| **Catamorphism** | ICD-10 code tree validation | Recursive tree fold for hierarchical code consistency |
| **Trampolining** | Deep ICD trees | Stack-safe recursion in Python |
