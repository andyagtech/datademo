# Functional Programming Analysis: CMS Claims Pipeline

## Current Architecture Overview

The existing pipeline uses an **imperative, mutable state** pattern:

```python
# Current: Mutable PipelineContext
@dataclass
class PipelineContext:
    results: dict[str, Any] = field(default_factory=dict)  # Mutable!
    halted: bool = False                                   # Mutable!
    con: duckdb.DuckDBPyConnection | None = None          # Side effects!
```

**6 Steps** mutate this context:
1. `step1_receive` → discovers files, writes to `ctx.results["receive"]`
2. `step2_schema_validate` → validates, writes to `ctx.results["schema_validate"]`
3. `step3_ingest` → creates DB tables, writes profiles
4. `step4_match` → builds match tables, runs validations
5. `step5_compare` → creates comparison tables
6. `step6_report` → generates HTML, exports CSV/Parquet

## Functional Programming Opportunities

### 1. Immutable Pipeline State (High Impact)

**Current Problem:**
```python
# Mutation makes reasoning hard, testing harder
def run(ctx: PipelineContext) -> StepResult:
    ctx.results["ingest"] = {...}  # Side effect
    ctx.con.execute("CREATE TABLE...")  # Side effect
    ctx.halted = True  # Side effect
```

**Functional Approach:**
```python
from typing import NamedTuple, Final
from functools import reduce

class PipelineState(NamedTuple):
    """Immutable pipeline state — each step returns a new state."""
    step_results: tuple[StepResult, ...]  # Immutable tuple
    db_snapshot: DBSnapshot  # DuckDB transactional state
    halted: bool
    halt_reason: str

# Pure function: same input → same output, no side effects
def step3_ingest(state: PipelineState, config: IngestConfig) -> PipelineState:
    if state.halted:
        return state  # Early return, no mutation
    
    # Transform data, return NEW state
    new_results = state.step_results + (ingest_result,)
    new_db = state.db_snapshot.apply(ingest_operations)
    
    return PipelineState(
        step_results=new_results,
        db_snapshot=new_db,
        halted=ingest_result.success is False,
        halt_reason=ingest_result.error or ""
    )
```

### 2. Railway-Oriented Programming for Error Handling

**Current Problem:**
```python
# Scattered error handling, halt flags, exceptions
def run_pipeline(ctx: PipelineContext) -> list[StepResult]:
    for step_name, step_fn in STEPS:
        if ctx.halted:  # Check flag
            break
        result = step_fn(ctx)  # Can raise, can mutate
        if not result.success:  # Check result
            ctx.halted = True  # Mutate
```

**Functional Approach (Result Monad):**
```python
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar('T')
E = TypeVar('E')

@dataclass(frozen=True)
class Result[T, E]:
    """Railway-oriented programming: Either success or failure."""
    value: T | None = None
    error: E | None = None
    
    def is_ok(self) -> bool: return self.error is None
    def is_err(self) -> bool: return self.error is not None
    
    def map(self, f: Callable[[T], T]) -> 'Result[T, E]':
        if self.is_err():
            return self
        return Result(value=f(self.value))
    
    def bind(self, f: Callable[[T], 'Result[T, E]']) -> 'Result[T, E]':
        """Monadic bind: chain operations that can fail."""
        if self.is_err():
            return self
        return f(self.value)

# Pure pipeline composition
def pipeline(state: PipelineState) -> Result[PipelineState, PipelineError]:
    return (
        Result(value=state)
        .bind(step1_receive)
        .bind(step2_schema_validate)
        .bind(step3_ingest)
        .bind(step4_match)
        .bind(step5_compare)
        .bind(step6_report)
    )
```

### 3. Lazy Evaluation with Generators

**Current Problem:**
```python
# Eager loading of all data
bene_matches = sorted(new_data_dir.glob("*Beneficiary*"))  # Load all
for p in bene_matches:  # Process all
    parts.append(...)
con.execute(f"CREATE TABLE...({' UNION ALL '.join(parts)})")
```

**Functional Approach:**
```python
from itertools import chain, islice
from typing import Iterator

def lazy_ingest(paths: Iterator[Path]) -> Iterator[Row]:
    """Lazy streaming: process rows as they're read, not all at once."""
    return (
        row 
        for path in paths
        for row in csv_rows(path)  # Generator
        if row_is_valid(row)       # Filter
    )

# Memory-efficient: process 4.7M claims as a stream
rows = lazy_ingest(new_data_dir.glob("*Carrier*"))
batched = batched(rows, n=10000)  # Process in chunks

# Or use functional composition
def ingest_pipeline(paths: list[Path]) -> Iterator[Row]:
    return pipe(
        paths,
        map(csv_rows),           # Extract
        chain.from_iterable,      # Flatten
        filter(row_is_valid),     # Validate
        map(add_derived_columns), # Transform
    )
```

### 4. Pure Data Transformations (No DB Side Effects)

**Current Problem:**
```python
# Direct DuckDB mutation
def _build_match_table(con, old_table, new_table, ...):
    con.execute(f"DROP TABLE IF EXISTS {match_table}")  # Side effect!
    con.execute(f"CREATE TABLE {match_table} AS...")     # Side effect!
```

**Functional Approach:**
```python
from pyarrow import Table as ArrowTable
import duckdb

def build_match_table(
    old_data: ArrowTable,
    new_data: ArrowTable,
    key_cols: list[str]
) -> tuple[ArrowTable, MatchStats]:
    """Pure function: takes tables, returns tables + stats. No DB mutation."""
    # Arrow/DuckDB as functional query engine
    return (
        old_data
        .join(new_data, keys=key_cols, join_type="full outer")
        .assign(match_status=lambda df: classify_match(df, key_cols))
    ), MatchStats(...)

# Compose pure transformations
def comparison_pipeline(
    old_bene: ArrowTable,
    new_bene: ArrowTable,
    old_claims: ArrowTable,
    new_claims: ArrowTable,
) -> ComparisonResult:
    return pipe(
        (old_bene, new_bene, old_claims, new_claims),
        lambda t: (
            match_beneficiaries(t[0], t[1]),
            match_claims(t[2], t[3])
        ),
        lambda m: compare_fields(m[0], m[1], COMPARISON_CONFIG),
        calculate_financial_impact,
        classify_discrepancies,
    )
```

### 5. Function Composition with Pipe Operator

```python
from functools import reduce
from typing import Callable, TypeVar

T = TypeVar('T')

def pipe(value: T, *functions: Callable[[T], T]) -> T:
    """Left-to-right function composition."""
    return reduce(lambda v, f: f(v), functions, value)

# Readable pipeline definition
pipeline = lambda initial_state: pipe(
    initial_state,
    step1_receive,
    step2_schema_validate,
    step3_ingest,
    step4_match,
    step5_compare,
    step6_report,
)

# Or use | operator with __or__ overload (like F# Elm)
result = initial_state | step1 | step2 | step3 | step4 | step5 | step6
```

### 6. Total Functions with Optional/Result

**Current Problem:**
```python
# Partial function: raises on bad input
def _extract_year_from_filename(filename: str) -> int | None:
    match = re.search(r"DE1_0_(\d{4})_Beneficiary", filename)
    return int(match.group(1)) if match else None  # None = partial
```

**Functional Approach:**
```python
from returns.maybe import Maybe, Some, Nothing
from returns.result import Result, Success, Failure

def extract_year(filename: str) -> Maybe[int]:
    """Total function: always returns a value (Some or Nothing)."""
    match = re.search(r"DE1_0_(\d{4})_Beneficiary", filename)
    return Some(int(match.group(1))) if match else Nothing

# Chain with bind
def process_beneficiary_file(path: Path) -> Result[BeneficiaryData, IngestError]:
    return (
        extract_year(path.name)
        .map(lambda year: (path, year))
        .bind(lambda t: load_csv(t[0]).map(lambda df: add_year(df, t[1])))
        .alt(lambda: Failure(IngestError(f"Cannot process {path}")))
    )
```

### 7. Immutable Data Structures

```python
from immutables import Map  # Persistent hash map
from pyrsistent import PVector, PMap

# Instead of mutable dict accumulation
results: dict[str, Any] = {}  # Current: mutable
results["profiles"] = profiles  # Mutation

# Use persistent data structures
results: PMap[str, Any] = pmap()  # Functional: returns new map
new_results = results.set("profiles", profiles)  # New map, old unchanged

# Structural sharing: efficient memory usage
# O(1) for get, O(log n) for set
```

## Recommended Migration Path

### Phase 1: Pure Transformations (Low Risk)
- Extract pure functions from steps (validation logic, comparison logic)
- Add property-based tests with Hypothesis
- Keep DB mutations at step boundaries

### Phase 2: Immutable State (Medium Risk)
- Replace `PipelineContext` with immutable `PipelineState`
- Use `frozen=True` dataclasses
- Replace list accumulation with tuple folding

### Phase 3: Railway-Oriented Error Handling (Medium Risk)
- Introduce `Result` type for step outcomes
- Replace halt flags with monadic composition
- Centralize error handling

### Phase 4: Lazy Evaluation (Higher Risk)
- Streaming ingestion for large files
- Generator-based processing pipeline
- Memory profiling required

### Phase 5: Arrow/DuckDB as Functional Query Engine (Research)
- Replace imperative SQL building with Arrow relational API
- Pure table transformations
- Write-once at step boundaries only

## Libraries to Consider

- **`returns`** — Monads (Maybe, Result, IO) for Python
- **`pyrsistent`** — Persistent data structures
- **`toolz`**/`**` — Functional utilities (curry, compose, pipe)
- **`pyarrow`** — Immutable columnar data (Arrow tables)
- **`hypothesis`** — Property-based testing for pure functions

## Example Refactor: Step 3 Ingest

**Current:**
```python
# Ingests, mutates DB, accumulates to ctx.results
@src/pipeline/step3_ingest.py:176-269
```

**Functional:**
```python
@dataclass(frozen=True)
class IngestConfig:
    old_beneficiary_paths: tuple[Path, ...]
    old_carrier_paths: tuple[Path, ...]
    new_beneficiary_paths: Maybe[tuple[Path, ...]]
    new_carrier_paths: Maybe[tuple[Path, ...]]

@dataclass(frozen=True)
class IngestResult:
    beneficiary_table: ArrowTable
    claims_table: ArrowTable
    new_beneficiary_table: Maybe[ArrowTable]
    new_claims_table: Maybe[ArrowTable]
    profiles: tuple[TableProfile, ...]
    anomalies: tuple[Anomaly, ...]
    stats: IngestStats

def ingest_step(config: IngestConfig) -> Result[IngestResult, IngestError]:
    """Pure: config → result or error. No side effects."""
    return pipe(
        config,
        validate_paths,
        load_beneficiaries,
        load_carrier_claims,
        profile_tables,
        detect_anomalies,
    )

# DB write is explicit, at the boundary
def persist_ingest(result: IngestResult, db: DuckDBConnection) -> None:
    """Effectful: only this function has side effects."""
    db.register("bene_temp", result.beneficiary_table)
    db.execute("CREATE TABLE beneficiary_summary AS SELECT * FROM bene_temp")
    # ... etc
```

## Testing Benefits

With pure functions:
```python
# Property-based testing
@given(st.dataframes(columns=[...]))
def test_beneficiary_matching_is_symmetric(df):
    """match(old, new) should be inverse of match(new, old)."""
    result1 = match_beneficiaries(df, df)
    result2 = match_beneficiaries(df, df)  # Same input
    assert result1 == result2  # Referential transparency

# No mocking needed
@given(st.lists(st.from_type(Path)))
def test_file_discovery_finds_all_csvs(paths):
    with temp_dir(paths) as d:
        result = discover_files(d)
        assert len(result) == len([p for p in paths if p.suffix == '.csv'])
```

## Summary

The current pipeline is **imperative with scattered state mutations**. A functional refactor would:

1. **Make state flow explicit** — No hidden mutations
2. **Enable property-based testing** — Referential transparency
3. **Simplify parallelization** — Immutable data is thread-safe
4. **Improve error handling** — Railway-oriented with Result types
5. **Enable optimizations** — Lazy evaluation, memoization

The biggest win would be **Phase 2 (Immutable State)** and **Phase 3 (Railway Errors)**, which are achievable without changing the DuckDB architecture.
