# Imperative vs Functional: A Balanced Comparison

This document provides an honest, side-by-side comparison of the two pipeline
implementations: the original imperative approach and the functional refactor.
Both have strengths. The goal is to show where functional programming delivers
real benefits and where it introduces new costs.

---

## Table of Contents

1. [Architecture at a Glance](#architecture-at-a-glance)
2. [Side-by-Side: Every Weakness Addressed](#side-by-side-every-weakness-addressed)
3. [What the Imperative Approach Does Well](#what-the-imperative-approach-does-well)
4. [Honest Trade-offs of the Functional Approach](#honest-trade-offs-of-the-functional-approach)
5. [Quantitative Comparison](#quantitative-comparison)
6. [When to Use Which](#when-to-use-which)
7. [Verdict](#verdict)

---

## Architecture at a Glance

### Imperative Pipeline

```
main.py → runner.py (for-loop over mutable PipelineContext)
  ├── step1_receive.py      ← mutates ctx.results["receive"]
  ├── step2_schema_validate  ← mutates ctx.results["schema_validate"]
  ├── step3_ingest           ← mutates ctx.con, ctx.results["ingest"]
  ├── step4_match            ← mutates ctx.results["match"]
  ├── step5_compare          ← mutates ctx.results["compare"]
  └── step6_report           ← mutates ctx.results["report"]

State model: One mutable PipelineContext shared by all steps
Error model: Boolean flags + exceptions + result.success checks
Data flow:   ctx.results[key] = {...}  (dict of dicts, untyped)
```

### Functional Pipeline

```
main.py → runner_fp.py (compose_pipeline — railway composition)
  ├── step1_functional       ← Pure: Result[PipelineState, Exception]
  ├── step2_functional       ← Pure: Result[PipelineState, Exception]
  ├── step3_functional(ctx)  ← Interpreter: IngestPlan → execute
  ├── step4_functional(ctx)  ← Z-set: TableRef → execute_diff
  ├── step5_functional(ctx)  ← Z-set: field diffs + trends
  └── step6_functional(ctx)  ← Interpreter: ReportPlan → execute

State model: Immutable PipelineState (frozen dataclass, new copy each step)
Error model: Result monad with automatic short-circuit
Data flow:   state.with_outcome(StepOutcome(...))  (typed, immutable)
```

---

## Side-by-Side: Every Weakness Addressed

### 1. Mutable Shared State → Immutable State 🔴→✅

**Imperative:**
```python
# Any step can mutate anything at any time
ctx.results["ingest"] = {"beneficiary_count": count}  # Mutation
ctx.halted = True                                       # Mutation
ctx.con = get_connection(db_path)                       # Mutation
```

**Functional:**
```python
# Each step returns a NEW state — the old one is untouched
new_state = state.with_outcome(StepOutcome(
    step_name="ingest",
    data={"beneficiary_count": count},
))
# state is still the original — frozen, immutable, safe
```

**What changed:** `PipelineState` and all data types are `@dataclass(frozen=True)`.
The `with_outcome()` method returns a new object. No step can corrupt another
step's data because the previous state physically cannot be modified.

**Remaining gap:** Steps 3-6 still close over a mutable `PipelineContext` for
database access. The `ctx.con` and `ctx.results` are mutated at the boundary.
This is deliberate — "functional core, imperative shell" — but it means the
functional purity doesn't extend to the DB layer.

---

### 2. Scattered Error Handling → Railway Pattern 🔴→✅

**Imperative (4 different mechanisms):**
```python
# runner.py — mixed error handling
for step_fn in steps:
    if ctx.halted:                    # Mechanism 1: flag check
        break
    try:
        result = step_fn(ctx)         # Mechanism 2: might raise
    except Exception as e:
        ctx.halted = True             # Mechanism 3: flag mutation
        break
    if not result.success:            # Mechanism 4: result check
        ctx.halted = True
        ctx.halt_reason = result.message
```

**Functional (one mechanism):**
```python
# compose_pipeline — single error model
pipeline = compose_pipeline(step1, step2, step3, step4, step5, step6)
final = pipeline(initial_state)
# If ANY step returns Failure, all subsequent steps are skipped automatically
# If ANY step sets success=False, state.should_halt() triggers on next step
```

**What changed:** Every step returns `Result[PipelineState, Exception]`. The
`compose_pipeline` function chains them with automatic short-circuit. There's
exactly one error model, not four.

**Remaining gap:** Inside each step, error handling is still procedural (try/except
around DB calls). The railway only operates at the step-to-step boundary.

---

### 3. Database as Implicit State → Interpreter Pattern 🔴→🟡

**Imperative (SQL scattered everywhere):**
```python
# step3_ingest.py
con.execute(f"DROP TABLE IF EXISTS {table}")
con.execute(f"CREATE TABLE {table} AS ({union_query})")
# step4_match.py
con.execute(f"CREATE TABLE _match_beneficiary AS ...")
# step5_compare.py
con.execute(f"CREATE TABLE _discrepancy_detail AS ...")
```

**Functional (pure description → single execution point):**
```python
# Pure: build a plan (no DB access)
plan = _build_ingest_plan(state.config)

# Pure: generate SQL (no DB access)
sql = diff_sql(old_ref, new_ref, "_zset_beneficiary")

# Effectful: one interpreter executes everything
con_result = _execute_ingest_plan(plan, ctx)
zset_result = execute_diff(con, old_ref, new_ref, ...)
```

**What changed:** SQL generation is pure (testable without a database). Execution
happens at a single boundary function per step.

**Remaining gap:** The boundary functions still call `con.execute()` directly.
A full free monad approach (see FUNCTIONAL_CONCEPTS.md §21) would make the
interpreter swappable, but that's future work. The interpreter pattern is a
pragmatic middle ground: SQL generation is pure, execution is contained.

---

### 4. No Type Safety → Typed Dataclasses 🟡→✅

**Imperative:**
```python
ctx.results["ingest"] = {
    "beneficiary_count": bene_count,    # What type? Runtime only
    "claims_count": claim_count,        # Typo "clams_count"? No error
    "anomalies": anomalies,             # list of what?
}
# Later:
count = ctx.results["ingest"]["beneficary_count"]  # KeyError at runtime
```

**Functional:**
```python
@dataclass(frozen=True)
class StepOutcome:
    step_name: str
    success: bool
    message: str
    data: dict[str, Any]                # Still dict internally...
    errors: tuple[str, ...]             # ...but tuples are typed
    warnings: tuple[str, ...]

# Z-set results are fully typed:
@dataclass(frozen=True)
class ZSetDiffResult:
    view: ZSetView
    stats: ZSetStats                    # .insertions, .deletions — IDE knows
    field_deltas: tuple[FieldDelta, ...]  # .column, .mismatch_count — typed
```

**What changed:** All new data structures are frozen dataclasses with typed fields.
Z-set results, anomaly checks, ingest plans, and file metadata are all typed.

**Remaining gap:** `StepOutcome.data` is still `dict[str, Any]` for backwards
compatibility with the report generator. A future step would replace this with
typed per-step result dataclasses.

---

### 5. Eager Evaluation → Lazy Descriptions 🟡→🟡

**Imperative:**
```python
bene_matches = sorted(glob("*Beneficiary*"))       # Immediate filesystem scan
parts = [f"SELECT..." for p in bene_matches]        # All queries built eagerly
con.execute(f"CREATE TABLE...({' UNION ALL '.join(parts)})")  # All at once
```

**Functional:**
```python
plan = _build_ingest_plan(state.config)  # Description only — no I/O yet
# plan.operations is a tuple of IngestOps — data, not actions
# Execution is deferred until _execute_ingest_plan() is called
```

**What changed:** Plans are built as pure data before execution. The `lazy()`
memoiser in `functional.py` supports deferred computation.

**Remaining gap:** DuckDB itself handles the actual data lazily (columnar
engine, predicate pushdown). The Python layer's laziness is at the operation
level, not the row level. True streaming would require a different execution
model (e.g., Feldera's incremental processing).

---

### 6. Tight DuckDB Coupling → Contained SQL Generation 🟡→🟡

**Imperative:**
```python
# SQL strings inline throughout step files
parts.append(f"SELECT *, {year} FROM read_csv_auto('{p}')")
con.execute(f"CREATE TABLE...({' UNION ALL '.join(parts)})")
```

**Functional:**
```python
# SQL generated by dedicated pure functions in zset.py
sql = diff_sql(old_ref, new_ref, result_table)   # Pure function
sql = stats_sql(result_table)                      # Pure function
sql = field_diff_sql(old, new, columns)            # Pure function
```

**What changed:** Z-set SQL generation is centralized in `zset.py`. Anomaly
check SQL is declared as data in `query_algebra.py`. Steps don't write raw SQL.

**Remaining gap:** Ingest SQL (CREATE TABLE, UNION ALL) is still built inline
in `_execute_ingest_plan`. The SQL dialect is still DuckDB-specific. Swapping
to another engine would require changing the SQL generators.

---

### 7. No Transaction Boundaries → Halt Propagation 🟡→🟡

**Imperative:**
```python
try:
    results = run_pipeline(ctx)  # Step 5 fails — steps 1-4 tables exist
finally:
    if ctx.con:
        ctx.con.close()          # DB closed, partial state remains
```

**Functional:**
```python
pipeline = compose_pipeline(step1, step2, step3, step4, step5, step6)
final = pipeline(initial_state)
# If step 3 fails, steps 4-6 are skipped (railway short-circuit)
# PipelineState records exactly which steps ran and which didn't
```

**What changed:** `compose_pipeline` ensures clean halt propagation. The
immutable `PipelineState` records exactly what happened — you can inspect
`state.outcomes` to see which steps succeeded and which failed.

**Remaining gap:** DuckDB tables created by earlier steps still persist on disk
after a later step fails. True transactional rollback would require wrapping the
entire pipeline in a DuckDB transaction, which the functional approach doesn't
yet do (same limitation as imperative).

---

### 8. Testability → Pure Functions + Property Tests 🔴→✅

**Imperative:**
```python
def test_step3():
    ctx = PipelineContext(old_data_dir=Path("fixtures/"), ...)  # Real paths
    result = step3_run(ctx)                                      # Creates real DB tables
    assert ctx.con.execute("SELECT COUNT(*) FROM beneficiary_summary").fetchone()[0] > 0
    # Slow, requires fixtures, not deterministic
```

**Functional:**
```python
# Pure function test — no DB, no files, instant
def test_diff_sql_structure():
    old = TableRef("old_table", ("id",))
    new = TableRef("new_table", ("id",))
    sql = diff_sql(old, new, "_zset_test")
    assert "FULL OUTER JOIN" in sql
    assert "_weight" in sql

# Property test — hundreds of random inputs, verifies algebraic laws
@given(st.integers())
def test_result_left_identity(x):
    assert Success(x).bind(f) == f(x)
```

**What changed:** 31 property-based tests verify monad laws, functor laws,
composition laws, and domain invariants. Pure functions can be tested without
any infrastructure. Z-set algebraic properties (identity, symmetry) are tested
with real DuckDB but on tiny synthetic data.

**This is the strongest win** of the functional approach. The imperative version
had 233 tests; the functional version has 264 — the extras are pure function
tests and property tests that would be impossible without referential transparency.

---

## What the Imperative Approach Does Well

The imperative approach has genuine strengths that shouldn't be dismissed:

### 1. Simplicity and Readability

```python
# Imperative: anyone can read this
con.execute(f"CREATE TABLE beneficiary_summary AS ({union_query})")
count = con.execute("SELECT COUNT(*) FROM beneficiary_summary").fetchone()[0]
logger.info(f"Loaded {count:,} records")
```

```python
# Functional: requires understanding Result, closures, composition
con_result = _execute_ingest_plan(plan, ctx)
if is_err(con_result):
    return Success(state.with_outcome(StepOutcome.err(...)))
con = con_result.unwrap()
```

The imperative version reads like a recipe. The functional version requires
understanding `Result`, `Success`, `StepOutcome.err`, `with_outcome`, and the
railway model before you can follow it.

### 2. Lower Learning Curve

A junior data engineer can understand and modify the imperative pipeline in an
afternoon. The functional pipeline requires familiarity with:
- Monads (`Result`, `Maybe`, `Success`, `Failure`)
- Railway-oriented programming
- The interpreter pattern
- Frozen dataclasses and immutable state
- Higher-order functions and closures
- The `returns` library API

### 3. Direct Debugging

```python
# Imperative: set a breakpoint, inspect ctx
ctx.results["ingest"]["beneficiary_count"]  # Just look at the dict

# Functional: need to unwrap Result, inspect frozen state
final_result.unwrap().outcomes[-1].data["beneficiary_count"]
```

Mutable state is easy to inspect in a debugger. Immutable state requires
navigating through layers of wrapping (`Result` → `PipelineState` → `StepOutcome`).

### 4. No Library Dependencies for Core Patterns

The imperative pipeline uses only standard Python idioms. The functional pipeline
depends on the `returns` library (third-party) for `Result` and `Maybe` types.
If `returns` breaks compatibility or is abandoned, the functional pipeline has
a harder migration path.

### 5. Familiar to Most Python Developers

Python is not Haskell. The language doesn't have native ADTs, tail-call
optimization, or a type system that enforces purity. Writing functional Python
is swimming against the current — `@dataclass(frozen=True)` is a convention,
not a compiler guarantee.

---

## Honest Trade-offs of the Functional Approach

### Costs Introduced

| Trade-off | Severity | Details |
|-----------|----------|---------|
| **Learning curve** | Medium | Developers need to understand monads, railway pattern, interpreter pattern |
| **`returns` library dependency** | Low | Third-party dep; could be vendored if needed |
| **Verbosity for simple operations** | Low | `Success(state.with_outcome(...))` vs `ctx.results[k] = v` |
| **Python's lack of native ADTs** | Medium | `frozen=True` is convention, not enforced; no exhaustive pattern matching |
| **Immutable copy overhead** | Negligible | `PipelineState` is tiny; real data lives in DuckDB |
| **Closure complexity** | Low | Steps 3-6 are closure factories — one more layer of indirection |
| **Debugging indirection** | Low | Must unwrap `Result` → `PipelineState` → `StepOutcome` in debugger |
| **No tail-call optimization** | N/A | Not using recursion, so this doesn't apply yet |

### Benefits Gained

| Benefit | Severity | Details |
|---------|----------|---------|
| **Eliminates shared mutable state** | High | Entire class of bugs (race conditions, stale state) removed |
| **Single error model** | High | Railway pattern replaces 4 ad-hoc mechanisms |
| **Pure functions are trivially testable** | High | 31 new property tests, no mocks needed |
| **Z-set algebra surfaced new findings** | High | Discovered beneficiary swap pattern the imperative version missed |
| **Interpreter pattern isolates I/O** | Medium | SQL generation testable without DB |
| **Typed results** | Medium | Frozen dataclasses catch errors at definition time |
| **Composable pipeline** | Medium | Adding/removing/reordering steps is a one-line change |
| **Immutable audit trail** | Medium | `state.outcomes` is append-only, tamper-proof history |
| **Pattern matching on errors** | Low | Structured `PipelineError` enables targeted handling |

---

## Quantitative Comparison

| Metric | Imperative | Functional | Notes |
|--------|-----------|------------|-------|
| **Tests passing** | 233 | 264 | +31 property tests, algebraic law verification |
| **Test categories** | Unit, integration | Unit, integration, property, algebraic | Property tests verify laws that hold for all inputs |
| **Pipeline runtime** | ~44s | ~44s | No measurable performance difference |
| **Lines of code (pipeline)** | ~1,200 | ~1,800 | +50% — additional abstractions, types, tests |
| **Error handling mechanisms** | 4 | 1 | Railway pattern replaces flags + exceptions + checks |
| **Mutable state locations** | 15+ (ctx mutations) | 3 (ctx.con, ctx.results at boundary) | 80% reduction in mutation points |
| **Pure functions (testable without I/O)** | ~0 | ~25 | SQL generators, validators, composers |
| **New findings** | — | Beneficiary swap pattern | Z-set algebra enabled structured follow-up queries |

---

## When to Use Which

### Use the imperative approach when:
- The team is primarily junior Python developers
- The pipeline is simple (< 3 steps, no cross-system comparison)
- Quick prototyping matters more than long-term maintenance
- There's no need for formal correctness guarantees

### Use the functional approach when:
- Data integrity is critical (healthcare, financial, government)
- The pipeline will be maintained by a team over years
- You need formal properties (monad laws, algebraic invariants)
- Testing without infrastructure (no DB, no filesystem) is valuable
- You're doing set-theoretic operations (diffs, matches) where Z-set algebra applies
- The team has functional programming experience or is willing to learn

---

## Verdict

The functional refactor is **not a rewrite for its own sake**. It solves real
problems that the imperative version had:

1. **Mutable state bugs** → eliminated by frozen dataclasses
2. **Inconsistent error handling** → unified by railway pattern
3. **Untestable core logic** → 31 new property tests on pure functions
4. **Missing analytical capability** → Z-set algebra found the beneficiary swap

The cost is complexity: more abstractions, a steeper learning curve, and a
dependency on the `returns` library. For a healthcare data pipeline where
correctness matters and the team can handle the abstractions, the trade-off
is worth it.

For a quick one-off script? Stick with imperative. It's simpler and faster to
write.
