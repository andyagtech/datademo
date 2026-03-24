# Current Pipeline Summary & Weaknesses Analysis

## Pipeline Architecture

The pipeline follows a **6-step sequential architecture** with shared mutable state:

```
┌─────────────────────────────────────────────────────────────────┐
│                    PipelineContext (Mutable State)                │
│  ┌──────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ Paths        │  │ DuckDB con  │  │ results: dict[str, Any] │ │
│  │ - old_data   │  │ (side eff.) │  │ - receive               │ │
│  │ - new_data   │  │             │  │ - schema_validate       │ │
│  │ - db_path    │  │             │  │ - ingest                │ │
│  │              │  │             │  │ - match                 │ │
│  │ Halt flags   │  │             │  │ - compare               │ │
│  │ - halted     │  │             │  │ - report                │ │
│  │ - halt_reason│  │             │  │                         │ │
│  └──────────────┘  └─────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   ┌─────────┐         ┌─────────┐           ┌─────────┐
   │ Step 1  │────────▶│ Step 2  │─────────▶  │ Step 3  │
   │ RECEIVE │         │ SCHEMA  │           │ INGEST  │
   └─────────┘         │ VALIDATE│           │ PROFILE │
        │              └─────────┘           └─────────┘
        │                                    (Creates DB
        │                                     tables)
   Discovers files                          Profiles data
   Extracts zips                            Detects anomalies
   Builds inventory
        │
        ▼
   ┌─────────┐         ┌─────────┐           ┌─────────┐
   │ Step 4  │────────▶│ Step 5  │─────────▶  │ Step 6  │
   │ MATCH   │         │ COMPARE │           │ REPORT  │
   │VALIDATE │         │ ANALYZE │           │ GENERATE│
   └─────────┘         └─────────┘           └─────────┘
                              │
   Record matching            Field diffs              HTML output
   Full outer joins          Trend analysis           CSV/Parquet exports
   Consistency checks        Financial reconciliation
```

## Step-by-Step Implementation

### Step 1: RECEIVE (step1_receive.py)
- **Input:** File paths (directory or zip)
- **Functions:** `_discover_files()`, `_extract_zip()`, `_inventory_files()`
- **Output:** File inventory with SHA-256 checksums
- **Storage:** `ctx.results["receive"]` with discovered/old_system/new_system
- **Validation:** 3 beneficiary files + 2 carrier claims files minimum

### Step 2: SCHEMA VALIDATE (step2_schema_validate.py)
- **Input:** CSV file paths from Step 1
- **Functions:** `_validate_headers()`, `_validate_types()`, `validate_file()`
- **Output:** Per-file validation results (valid/invalid with errors)
- **Storage:** `ctx.results["schema_validate"]` with file_validations list
- **Gate:** Halt pipeline if any file invalid

### Step 3: INGEST & PROFILE (step3_ingest.py)
- **Input:** Validated CSV paths
- **Functions:** `ingest_beneficiary_summaries()`, `ingest_carrier_claims()`, `ingest_new_system()`, `profile_run()`, `_detect_anomalies()`
- **Output:** DuckDB tables (beneficiary_summary, carrier_claims, new_* versions)
- **Storage:** `ctx.results["profiles"]`, `ctx.results["anomalies"]`
- **DB Operations:** `read_csv_auto()` → `CREATE TABLE` → profiling SQL

### Step 4: MATCH & VALIDATE (step4_match.py)
- **Input:** DuckDB connection with ingested tables
- **Functions:** `_build_match_table()` (FULL OUTER JOIN), `validate_run()` (95 checks)
- **Output:** Match tables (_match_beneficiary, _match_claims)
- **Storage:** `ctx.results["match"]` with match_results, validation counts
- **SQL Pattern:**
```sql
CREATE TABLE _match_beneficiary AS
SELECT COALESCE(o.DESYNPUF_ID, n.DESYNPUF_ID) as DESYNPUF_ID,
       CASE WHEN o.DESYNPUF_ID IS NULL THEN 'new_only'
            WHEN n.DESYNPUF_ID IS NULL THEN 'old_only'
            ELSE 'matched' END as match_status
FROM beneficiary_summary o
FULL OUTER JOIN new_beneficiary_summary n 
  ON CAST(o.DESYNPUF_ID AS VARCHAR) = CAST(n.DESYNPUF_ID AS VARCHAR)
```

### Step 5: COMPARE & ANALYZE (step5_compare.py)
- **Input:** DuckDB connection, match tables
- **Functions:** `compare_run()` (129 comparisons), `_build_discrepancy_detail()`
- **Output:** Discrepancy tables (_discrepancy_detail), trend analysis
- **Storage:** `ctx.results["comparisons"]`, `ctx.results["trends"]`
- **Analysis:** Field-level diffs, financial reconciliation, phantom record detection

### Step 6: REPORT (step6_report.py)
- **Input:** All previous results, DuckDB connection
- **Functions:** `report_run()` (Jinja2 HTML generation), CSV/Parquet exports
- **Output:** `comparison_report.html`, `exports/*.csv`, `exports/*.parquet`
- **Storage:** `ctx.results["report"]` with paths to generated files

---

## Critical Weaknesses

### 1. Mutable Shared State 🔴 HIGH
```python
# PROBLEM: Hidden mutations throughout pipeline
ctx.results["ingest"] = {...}           # Mutation 1
ctx.con.execute("CREATE TABLE...")      # Side effect 1
ctx.halted = True                       # Mutation 2
ctx.halt_reason = "..."                 # Mutation 3
```
**Impact:** Unpredictable state, race conditions, hard to test, no state guarantees

### 2. Scattered Error Handling 🔴 HIGH
```python
# PROBLEM: 4 different error mechanisms
if ctx.halted:                    # Mechanism 1: Flag check
    break
result = step_fn(ctx)             # Can raise exception (Mech 2)
if not result.success:            # Mechanism 3: Result check
    ctx.halted = True             # Mechanism 4: State mutation
```
**Impact:** Inconsistent propagation, missed cases, no compile-time safety

### 3. Database as Implicit State 🔴 HIGH
```python
# PROBLEM: Side effects hidden in SQL
con.execute(f"DROP TABLE IF EXISTS {table}")   # Mutation
con.execute(f"CREATE TABLE {table} AS ...")   # Mutation
```
**Impact:** Tests require real DB, not idempotent, can't inspect intermediate state

### 4. No Type Safety on Results 🟡 MEDIUM
```python
ctx.results["ingest"] = {
    "beneficiary_count": int,
    "claims_count": int,
    "anomalies": list[Anomaly],  # What's Anomaly? Runtime only.
}
# Dict[str, Any] = essentially untyped
```
**Impact:** No IDE autocomplete, runtime typos, dangerous refactoring

### 5. Eager Evaluation 🟡 MEDIUM
```python
# PROBLEM: Loads all data eagerly
bene_matches = sorted(glob("*Beneficiary*"))  # All files
parts = [f"SELECT..." for p in bene_matches]  # All queries
con.execute(f"CREATE TABLE...({ ' UNION ALL '.join(parts) })")
```
**Impact:** Memory spikes (4.7M claims), can't process partial data, no streaming

### 6. Tight DuckDB Coupling 🟡 MEDIUM
```python
# SQL strings scattered throughout
parts.append(f"SELECT *, {year} FROM read_csv_auto('{p}')")
con.execute(f"CREATE TABLE...({' UNION ALL '.join(parts)})")
```
**Impact:** Can't swap engines, SQL injection risk, hard to unit test

### 7. No Transaction Boundaries 🟡 MEDIUM
```python
try:
    results = run_pipeline(ctx)  # Step 5 fails, steps 1-4 tables exist
finally:
    if ctx.con:
        ctx.con.close()          # DB closed anyway
```
**Impact:** Partial state on failure, no rollback, re-run issues

### 8. Testability Issues 🔴 HIGH
```python
def test_step3():
    ctx = PipelineContext(...)  # Needs real paths
    result = step3_run(ctx)     # Creates real tables
    # How to verify? Query the DB? Complex fixtures.
```
**Impact:** No pure function tests, slow I/O tests, complex fixtures

### 9. Logging as Primary Observation 🟢 LOW
```python
logger.info(f"Loaded {count} records...")  # Side effect for observability
```
**Impact:** Can't programmatically inspect, log parsing for metrics

### 10. Configuration vs. Code Blur 🟢 LOW
```python
FILE_PATTERNS = {"beneficiary": "*Beneficiary*"}  # Hardcoded
EXPECTED_MIN_COUNTS = {"beneficiary": 3}           # Hardcoded
```
**Impact:** Changing patterns requires code edits, no external config

---

## Weakness Summary Table

| Weakness | Severity | Functional Solution |
|----------|----------|---------------------|
| Mutable shared state | 🔴 High | Immutable `PipelineState` |
| Scattered error handling | 🔴 High | `Result[T, E]` monad |
| DB as implicit state | 🔴 High | Pure transformations, explicit persistence |
| No type safety | 🟡 Medium | Typed `PipelineState`, dataclasses |
| Eager evaluation | 🟡 Medium | Lazy generators, streaming |
| Tight DuckDB coupling | 🟡 Medium | Abstract data operations |
| No transactions | 🟡 Medium | Atomic state updates |
| Testability | 🔴 High | Pure functions, property tests |
| Logging observability | 🟢 Low | Structured events |
| Config/code blur | 🟢 Low | External configuration |

---

## Files Affected

| File | Responsibility | Weaknesses Present |
|------|---------------|-------------------|
| `src/pipeline/__init__.py` | PipelineContext, StepResult | Mutable dataclass, untyped results |
| `src/pipeline/runner.py` | run_pipeline() orchestration | Scattered error handling, halt flags |
| `src/pipeline/step1_receive.py` | File discovery, zip extraction | Eager loading, hardcoded patterns |
| `src/pipeline/step2_schema_validate.py` | CSV validation | SQL coupling, eager file reading |
| `src/pipeline/step3_ingest.py` | DuckDB ingest, profiling | DB mutations, eager loading |
| `src/pipeline/step4_match.py` | Record matching, validation | DB mutations (CREATE TABLE) |
| `src/pipeline/step5_compare.py` | Field comparison, trends | DB mutations, tight SQL coupling |
| `src/pipeline/step6_report.py` | HTML generation, exports | Side effects (file writes), DB reads |
| `src/ingest.py` | Legacy ingest functions | DB mutations, eager evaluation |
| `src/main.py` | CLI entry point | Scattered error handling |

---

Document created: 2026-03-23
Branch: functional_approach
Purpose: Baseline for functional refactoring
