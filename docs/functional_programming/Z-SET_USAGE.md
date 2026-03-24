# Z-Set Usage: A Complete Walkthrough

This document traces one complete Z-set calculation end-to-end, from pure SQL
generation through DuckDB execution to real results. The example uses the
beneficiary data (343,644 rows per system).

---

## Architecture: Two Layers

The Z-set implementation in `src/zset.py` has two layers:

- **Layer 1** — Pure SQL generators (`diff_sql`, `stats_sql`, `field_diff_sql`):
  functions that produce SQL strings but never touch the database. These are testable
  without any database connection.

- **Layer 2** — A single interpreter (`execute_diff`): the only function that actually
  executes SQL against DuckDB. It calls Layer 1 to get the SQL, then runs it.

Both layers execute during the pipeline. The separation is an engineering pattern
(the interpreter pattern) that makes the SQL generation independently testable.

---

## Entry Point: Step 4 Calls `execute_diff`

The journey starts in `src/pipeline/steps_fp.py` during Step 4 (Match & Validate).
The match configuration comes from `src/pipeline/query_algebra.py`:

```python
# From query_algebra.py — pure, immutable description of what to match
MatchConfig(
    old_table="beneficiary_summary",
    new_table="new_beneficiary_summary",
    key_cols=("DESYNPUF_ID", "summary_year"),
    compare_cols=("BENE_BIRTH_DT", "BENE_DEATH_DT", "BENE_SEX_IDENT_CD", ...),
    numeric_cols=("MEDREIMB_IP", "BENRES_IP", "PPPYMT_IP", "MEDREIMB_OP", ...),
    zset_table="_zset_beneficiary",
)
```

Step 4 builds `TableRef` objects and calls the interpreter:

```python
# From steps_fp.py — the call site
old_ref = TableRef(name="beneficiary_summary", key_cols=("DESYNPUF_ID", "summary_year"))
new_ref = TableRef(name="new_beneficiary_summary", key_cols=("DESYNPUF_ID", "summary_year"))

# This is where it actually executes
zset_result = execute_diff(con, old_ref, new_ref, "_zset_beneficiary")
```

---

## Inside `execute_diff`: The Interpreter

The interpreter in `src/zset.py` does three things in sequence:

```python
def execute_diff(con, old, new, result_table, compare_cols=(), numeric_cols=()):
    def _run():
        # 1. Generate and execute the diff SQL
        sql = diff_sql(old, new, result_table)          # Layer 1: pure
        for stmt in sql.strip().split(";"):             # Layer 2: execute
            con.execute(stmt)

        # 2. Generate and execute the stats SQL
        s_sql = stats_sql(result_table)                 # Layer 1: pure
        row = con.execute(s_sql).fetchone()             # Layer 2: execute
        stats = ZSetStats(...)

        # 3. Generate and execute field diff SQL (if columns specified)
        f_sql = field_diff_sql(old, new, ...)           # Layer 1: pure
        row = con.execute(f_sql).fetchone()             # Layer 2: execute
        field_deltas = [FieldDelta(...), ...]

        return ZSetDiffResult(view=..., stats=stats, field_deltas=tuple(field_deltas))

    return Success(_run())  # Wrapped in Result type
```

Let's trace each of these three operations.

---

## Step A → B: The Core Diff (Creating the Z-Set Table)

### What we start with

Two DuckDB tables, 343,644 rows each:

```
beneficiary_summary (old)          new_beneficiary_summary (new)
┌──────────────┬──────┬─────┐     ┌──────────────┬──────┬─────┐
│ DESYNPUF_ID  │ year │ ... │     │ DESYNPUF_ID  │ year │ ... │
├──────────────┼──────┼─────┤     ├──────────────┼──────┼─────┤
│ 002F1C637DB1 │ 2008 │     │     │ (absent)     │      │     │  ← removed
│ Alice123...  │ 2008 │     │     │ Alice123...  │ 2008 │     │  ← matched
│ Bob456...    │ 2009 │     │     │ Bob456...    │ 2009 │     │  ← matched
│ (absent)     │      │     │     │ NewGuy789... │ 2010 │     │  ← added
└──────────────┴──────┴─────┘     └──────────────┴──────┴─────┘
```

### The generated SQL

`diff_sql(old_ref, new_ref, "_zset_beneficiary")` produces:

```sql
DROP TABLE IF EXISTS _zset_beneficiary;
CREATE TABLE _zset_beneficiary AS
SELECT
    COALESCE(CAST(o.DESYNPUF_ID AS VARCHAR), CAST(n.DESYNPUF_ID AS VARCHAR)) AS DESYNPUF_ID,
    COALESCE(CAST(o.summary_year AS VARCHAR), CAST(n.summary_year AS VARCHAR)) AS summary_year,
    CASE
        WHEN o.DESYNPUF_ID IS NULL THEN 1     -- insertion (new only)
        WHEN n.DESYNPUF_ID IS NULL THEN -1    -- deletion (old only)
        ELSE 0                                 -- matched (cancels out)
    END AS _weight,
    CASE
        WHEN o.DESYNPUF_ID IS NULL THEN 'new_only'
        WHEN n.DESYNPUF_ID IS NULL THEN 'old_only'
        ELSE 'matched'
    END AS _status
FROM beneficiary_summary o
FULL OUTER JOIN new_beneficiary_summary n
    ON CAST(o.DESYNPUF_ID AS VARCHAR) = CAST(n.DESYNPUF_ID AS VARCHAR)
    AND CAST(o.summary_year AS VARCHAR) = CAST(n.summary_year AS VARCHAR)
```

### What it does

The `FULL OUTER JOIN` merges every row from both tables. If a row exists in both
(matched on key), both sides are non-null → weight = 0. If a row is only in the
old table, the new side is null → weight = -1. If only in the new table, the old
side is null → weight = +1.

This is the Z-set operation **Δ(R) = R_new − R_old** expressed as SQL.

### The actual result

After `con.execute()` runs this SQL, `_zset_beneficiary` is a real DuckDB table
with **343,803 rows**. Sample rows:

```
DESYNPUF_ID       year   _weight   _status
002F1C637DB1...   2008   -1        old_only     ← this person was removed
0278014838EF...   2008   -1        old_only     ← this person was removed
Alice123...       2008    0        matched      ← exists in both systems
Bob456...         2009    0        matched      ← exists in both systems
NewGuy789...      2010   +1        new_only     ← this person was added
```

---

## Step C: Stats (Counting the Weights)

### The generated SQL

`stats_sql("_zset_beneficiary")` produces:

```sql
SELECT
    COUNT(*) AS total_rows,
    SUM(CASE WHEN _weight > 0 THEN 1 ELSE 0 END) AS insertions,
    SUM(CASE WHEN _weight < 0 THEN 1 ELSE 0 END) AS deletions,
    SUM(CASE WHEN _weight = 0 THEN 1 ELSE 0 END) AS unchanged,
    SUM(_weight) AS net_change
FROM _zset_beneficiary
```

### The actual result

```
total_rows:  343,803
insertions:      159   (weight = +1, new only)
deletions:       159   (weight = -1, old only)
unchanged:   343,485   (weight =  0, matched)
net_change:        0   (insertions - deletions)
match_rate:    99.91%
```

`net_change = 0` means exactly as many were added as removed — a perfect swap.

These values are packed into an immutable `ZSetStats` dataclass:

```python
@dataclass(frozen=True)
class ZSetStats:
    total_rows: int      # 343,803
    insertions: int      # 159
    deletions: int       # 159
    unchanged: int       # 343,485
    net_change: int      # 0
```

---

## Step D: Field Delta (Drilling Into Matched Rows)

For the **343,485 matched rows** (weight = 0), we want to know: did any field
values actually change? We look at one specific column: `MEDREIMB_OP` (outpatient
Medicare reimbursement dollars).

### The generated SQL

`field_diff_sql(old_ref, new_ref, ("MEDREIMB_OP",), is_numeric=True)` produces:

```sql
SELECT
    COUNT(*) AS total_matched,
    SUM(CASE WHEN o."MEDREIMB_OP"::VARCHAR IS DISTINCT FROM n."MEDREIMB_OP"::VARCHAR
        THEN 1 ELSE 0 END) AS mismatch_medreimb_op,
    SUM(ABS(COALESCE(o."MEDREIMB_OP"::DOUBLE,0)
          - COALESCE(n."MEDREIMB_OP"::DOUBLE,0))) AS delta_sum_medreimb_op,
    AVG(ABS(COALESCE(o."MEDREIMB_OP"::DOUBLE,0)
          - COALESCE(n."MEDREIMB_OP"::DOUBLE,0))) AS delta_avg_medreimb_op,
    MAX(ABS(COALESCE(o."MEDREIMB_OP"::DOUBLE,0)
          - COALESCE(n."MEDREIMB_OP"::DOUBLE,0))) AS delta_max_medreimb_op
FROM beneficiary_summary o
INNER JOIN new_beneficiary_summary n
    ON o.DESYNPUF_ID = n.DESYNPUF_ID
    AND o.summary_year = n.summary_year
```

### The actual result

```
total matched rows:                343,485
rows with MEDREIMB_OP difference:       47
total dollar delta:             $10,924.62
average delta per row:               $0.03
largest single delta:            $5,339.95
```

Out of 343,485 matched beneficiaries, only **47** had a different outpatient
Medicare reimbursement value. The total dollar impact across those 47 is
**$10,924.62**.

These values are packed into an immutable `FieldDelta` dataclass:

```python
@dataclass(frozen=True)
class FieldDelta:
    column: str              # "MEDREIMB_OP"
    mismatches: int          # 47
    total_matched: int       # 343,485
    mismatch_pct: float      # 0.014%
    sum_abs_delta: float     # 10,924.62
    avg_abs_delta: float     # 0.03
    max_abs_delta: float     # 5,339.95
```

---

## Step E: The Actual Differing Rows

Those 47 differences are real people. The top 5 largest `MEDREIMB_OP` changes:

| Beneficiary ID | Year | Old System | New System | Delta |
|---------------|------|-----------|-----------|-------|
| 081F9E38AB06... | 2009 | $25,700.00 | $20,360.05 | $5,339.95 |
| B78309A6DF30... | 2009 | $6,490.00 | $7,846.32 | $1,356.32 |
| B00EDAD0D8C2... | 2010 | $2,680.00 | $3,348.90 | $668.90 |
| AAC9CB9A7B96... | 2010 | $2,040.00 | $2,549.57 | $509.57 |
| F89387D3FE77... | 2009 | $3,520.00 | $3,013.69 | $506.31 |

The largest: one beneficiary's 2009 outpatient Medicare reimbursement was revised
**downward** by $5,340 in the new system.

---

## How the Results Are Used

The `ZSetDiffResult` returned by `execute_diff` is consumed in two places:

1. **Step 4** uses the `ZSetStats` (matched/old_only/new_only counts) to populate
   the match results and calculate match rates.

2. **Step 5** uses the `FieldDelta` tuples to identify dollar-value divergences,
   aggregate them into a total financial impact ($35,624.71 across all fields),
   and feed them into the final HTML report.

The Z-set table itself (`_zset_beneficiary`) persists in DuckDB and is exported as
both CSV and Parquet in Step 6, making it available for ad-hoc analysis.

---

## Testing the Two Layers

### Layer 1 tests (pure, no database needed)

```python
class TestPureSqlGeneration:
    def test_diff_sql_contains_full_outer_join(self, old_ref, new_ref):
        sql = diff_sql(old_ref, new_ref, "_zset_test")
        assert "FULL OUTER JOIN" in sql
        assert "_weight" in sql
        assert "_status" in sql
```

### Layer 2 tests (small in-memory DuckDB)

```python
class TestExecuteDiff:
    def test_basic_diff(self, con, old_ref, new_ref):
        result = execute_diff(con, old_ref, new_ref, "_zset_test")
        assert is_ok(result)
        zr = result.unwrap()

        assert zr.stats.total_rows == 4  # Alice + Bob + Carol + Dave
        assert zr.stats.unchanged == 2   # Alice + Bob
        assert zr.stats.deletions == 1   # Carol (old only)
        assert zr.stats.insertions == 1  # Dave (new only)
```

### Algebraic property tests

```python
class TestZSetAlgebraicProperties:
    def test_identity_diff_is_empty(self):
        """A - A = {} (self-diff has no changes)."""
    def test_empty_new_is_all_deletions(self):
        """A - {} = A (everything is a deletion)."""
    def test_stats_sum_to_total(self):
        """insertions + deletions + unchanged == total."""
    def test_net_change_is_insertions_minus_deletions(self):
        """net_change == insertions - deletions."""
```

---

## Summary

The complete flow for one Z-set calculation:

1. **`query_algebra.py`** defines _what_ to diff (table names, key columns, comparison
   fields) as frozen dataclasses — no I/O.

2. **`steps_fp.py`** builds `TableRef` objects and calls `execute_diff` — the boundary
   between pure descriptions and effectful execution.

3. **`zset.py` Layer 1** (`diff_sql`, `stats_sql`, `field_diff_sql`) generates the SQL
   strings — pure functions, independently testable.

4. **`zset.py` Layer 2** (`execute_diff`) runs those SQL strings against DuckDB,
   creating real tables with `_weight` columns, and wraps the results in immutable
   `ZSetDiffResult` objects.

5. **DuckDB** does all the heavy computation — the `FULL OUTER JOIN` across 343,644
   rows per side executes in seconds using its columnar engine. Python never loads
   the data into memory.
