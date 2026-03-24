# Data Pipeline Reference

> Canonical documentation for the CMS Claims Data Comparison Pipeline.
> For architecture diagrams, see [`docs/architecture.html`](architecture.html).
> For design rationale, see [`docs/SOLUTION.md`](SOLUTION.md).

---

## Table of Contents

1. [Pipeline Overview](#pipeline-overview)
2. [Step 1 — Receive & Verify](#step-1--receive--verify)
3. [Step 2 — Schema Validate](#step-2--schema-validate)
4. [Step 3 — Ingest & Profile](#step-3--ingest--profile)
5. [Step 4 — Match & Validate](#step-4--match--validate)
6. [Step 5 — Compare & Analyze](#step-5--compare--analyze)
7. [Step 6 — Report](#step-6--report)
8. [Data Model](#data-model)
9. [Validation Checks Reference](#validation-checks-reference)
10. [Comparison Checks Reference](#comparison-checks-reference)
11. [Output Artifacts](#output-artifacts)

---

## Pipeline Overview

```
CSV Files (old + new system)
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 1: Receive & Verify     — file discovery, checksums        │
│  Step 2: Schema Validate      — header checks, file classification│
│  Step 3: Ingest & Profile     — DuckDB loading, column profiling │
│  Step 4: Match & Validate     — FULL OUTER JOIN, consistency     │
│  Step 5: Compare & Analyze    — field-level diffs, aggregates    │
│  Step 6: Report               — JSON data + HTML + CSV exports   │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
reports/report_data.json        (canonical data artifact)
reports/comparison_report.html  (interactive HTML report)
reports/exports/*.csv           (raw diff tables)
```

**Execution model:** Each step is a pure function `run(ctx: PipelineContext) -> StepResult`. The runner (`src/pipeline/runner.py`) calls them in sequence. If any step sets `ctx.halted = True`, the pipeline stops with a clear error message. The same functions run locally (sequential) or in AWS (Step Functions + Lambda).

**Key types:**
- `PipelineContext` — carries the DuckDB connection, config, storage adapter, and accumulated results across steps.
- `StepResult` — returned by each step with `success`, `message`, `errors[]`, `warnings[]`, and step-specific data.

---

## Step 1 — Receive & Verify

**Source:** `src/pipeline/step1_receive.py`

**Purpose:** Discover input CSV files, verify integrity, build a complete file inventory.

**Process:**
1. Scan `data/original_downloads/` for ZIP archives and `data/old_system/` for extracted CSVs (or S3 bucket via `StorageAdapter`).
2. If a `--new-data` path is provided, scan it separately for new system files.
3. Extract any `.zip` archives found.
4. Compute SHA-256 checksums for integrity verification.
5. Record file metadata: name, path, size (MB), checksum.

**Outputs stored in `ctx.results["receive"]`:**
```python
{
    "old_system": {
        "source_dir": "data/",
        "inventory": {
            "DE1_0_2008_Beneficiary_Summary_File_Sample_1.csv": {
                "path": "data/DE1_0_2008_Beneficiary_...",
                "size_mb": 28.4,
                "checksum": "sha256:abc123..."
            },
            ...
        }
    },
    "new_system": {
        "source_dir": "data/new_system/...",
        "inventory": { ... }
    }
}
```

**Halt condition:** No CSV files found in the data directory.

---

## Step 2 — Schema Validate

**Source:** `src/pipeline/step2_schema_validate.py`

**Purpose:** Validate CSV headers before the expensive ingestion step. Fail fast on malformed input.

**Process:**
1. Read only the first row (header) of each CSV — no full data scan.
2. Classify each file as **beneficiary** or **carrier claims** based on header fingerprints:
   - Beneficiary files contain `BENE_BIRTH_DT`, `BENE_SEX_IDENT_CD`, etc. (32 expected columns)
   - Carrier claims files contain `CLM_ID`, `CLM_FROM_DT`, `LINE_NCH_PMT_AMT_1`, etc. (141 expected columns)
3. Check for missing required columns and unexpected extra columns.
4. Report schema errors per file.

**Outputs stored in `ctx.results["schema_validate"]`:**
```python
{
    "validated_count": 10,
    "beneficiary_count": 6,
    "carrier_count": 4,
    "schema_errors": []
}
```

**Halt condition:** Any file has missing required columns.

---

## Step 3 — Ingest & Profile

**Source:** `src/pipeline/step3_ingest.py`, `src/ingest.py`, `src/profile.py`

**Purpose:** Load all CSVs into DuckDB in-memory tables and compute column-level quality profiles.

### Ingestion (`src/ingest.py`)

| Function | Tables Created | Notes |
|----------|---------------|-------|
| `ingest_beneficiary_summaries()` | `beneficiary_summary` | Reads 3 yearly CSVs, adds `summary_year` column extracted from filename (e.g., `DE1_0_2008_...` → `2008`) |
| `ingest_carrier_claims()` | `carrier_claims` | Reads 2 CSVs (Sample_1A + Sample_1B), `UNION ALL` |
| `ingest_new_system()` | `new_beneficiary_summary`, `new_carrier_claims` | Same logic, adds `summary_year` for beneficiary files |

All ingestion uses DuckDB's `read_csv_auto()` with `header=true` and automatic type inference.

### Profiling (`src/profile.py`)

For every column in every table, computes:

| Metric | Description |
|--------|-------------|
| `null_count` | Number of NULL values |
| `null_pct` | Percentage NULL |
| `distinct_count` | Number of distinct values |
| `min_val` | Minimum value |
| `max_val` | Maximum value |
| `mean_val` | Mean (numeric columns only) |
| `dtype` | Inferred DuckDB data type |

**Anomaly detection** flags:
- Columns with >50% NULL values (high-null)
- Zero-variance columns (all values identical)
- Potential outlier distributions

**Outputs:** `ctx.results["profiles"]` — a `dict[str, TableProfile]` mapping table names to their profiles.

---

## Step 4 — Match & Validate

**Source:** `src/pipeline/step4_match.py`, `src/validate.py`

This step does two things in parallel:
1. **Record matching** — joins old and new system tables
2. **Internal validation** — checks old system data quality

### Record Matching (`step4_match.py`)

For each table pair, performs a `FULL OUTER JOIN` on primary keys:

| Table Pair | Join Key | Why This Key |
|------------|----------|--------------|
| `beneficiary_summary` ↔ `new_beneficiary_summary` | `(DESYNPUF_ID, summary_year)` | Composite key — same beneficiary appears once per year |
| `carrier_claims` ↔ `new_carrier_claims` | `CLM_ID` | Unique claim identifier |

**Key implementation detail:** All join keys are `CAST(...  AS VARCHAR)` to handle type mismatches (e.g., `CLM_ID` is `BIGINT` in one table, `VARCHAR` in the other).

Every record is classified into one of three categories:

| Classification | Meaning | How Detected |
|----------------|---------|--------------|
| `matched` | Exists in both systems | `COALESCE(old_key, new_key)` is not null on both sides |
| `old_only` | In old system, missing from new | `new_key IS NULL` after FULL OUTER JOIN |
| `new_only` | In new system, not in old | `old_key IS NULL` after FULL OUTER JOIN |

Results are stored in DuckDB tables `_match_beneficiary` and `_match_claims`.

### Internal Validation (`src/validate.py`)

Runs 19 checks organized into 6 categories against the **old system data** to establish a quality baseline. Each check is a standalone function that runs a SQL query, counts violations, and returns a `ValidationResult`.

> **See [Validation Checks Reference](#validation-checks-reference) below for the complete check-by-check breakdown.**

---

## Step 5 — Compare & Analyze

**Source:** `src/pipeline/step5_compare.py`, `src/compare.py`

**Purpose:** For every matched record pair, compare each field value between old and new systems. Quantify discrepancies by column, category, and financial impact.

Runs 110 checks organized into 4 categories against two table pairs. Each check returns a `ComparisonResult`.

> **See [Comparison Checks Reference](#comparison-checks-reference) below for the complete check-by-check breakdown.**

### Table Pair Configuration (`compare.py → TABLE_PAIRS`)

```python
TABLE_PAIRS = [
    {
        "old": "beneficiary_summary",
        "new": "new_beneficiary_summary",
        "key": ["DESYNPUF_ID", "summary_year"],
        "compare_cols": [
            "BENE_BIRTH_DT", "BENE_DEATH_DT", "BENE_SEX_IDENT_CD", "BENE_RACE_CD",
            "BENE_ESRD_IND", "SP_STATE_CODE", "BENE_COUNTY_CD",
            "BENE_HI_CVRAGE_TOT_MONS", "BENE_SMI_CVRAGE_TOT_MONS",
            "BENE_HMO_CVRAGE_TOT_MONS", "PLAN_CVRG_MOS_NUM",
            "SP_ALZHDMTA", "SP_CHF", "SP_CHRNKIDN", "SP_CNCR", "SP_COPD",
            "SP_DEPRESSN", "SP_DIABETES", "SP_ISCHMCHT", "SP_OSTEOPRS", "SP_RA_OA",
            "SP_STRKETIA",
        ],
        "numeric_cols": [
            "MEDREIMB_IP", "BENRES_IP", "PPPYMT_IP",
            "MEDREIMB_OP", "BENRES_OP", "PPPYMT_OP",
            "MEDREIMB_CAR", "BENRES_CAR", "PPPYMT_CAR",
        ],
    },
    {
        "old": "carrier_claims",
        "new": "new_carrier_claims",
        "key": ["CLM_ID"],
        "compare_cols": [
            "DESYNPUF_ID", "CLM_FROM_DT", "CLM_THRU_DT",
            "ICD9_DGNS_CD_1", ..., "ICD9_DGNS_CD_8",       # 8 diagnosis codes
            "HCPCS_CD_1", ..., "HCPCS_CD_13",               # 13 procedure codes
            "PRF_PHYSN_NPI_1", ..., "PRF_PHYSN_NPI_5",       # 5 provider NPIs
            "TAX_NUM_1", ..., "TAX_NUM_5",                   # 5 tax numbers
            "LINE_PRCSG_IND_CD_1", ..., "_5",                # 5 processing indicators
            "LINE_ICD9_DGNS_CD_1", ..., "_5",                # 5 line diagnosis codes
        ],                                                    # 44 columns total
        "numeric_cols": [
            "LINE_NCH_PMT_AMT_1", ..., "_5",                 # 5 payment amounts
            "LINE_BENE_PTB_DDCTBL_AMT_1", ..., "_5",         # 5 deductibles
            "LINE_BENE_PRMRY_PYR_PD_AMT_1", ..., "_3",       # 3 primary payer
            "LINE_COINSRNC_AMT_1", ..., "_5",                 # 5 coinsurance
            "LINE_ALOWD_CHRG_AMT_1", ..., "_5",               # 5 allowed charges
        ],                                                    # 23 columns total
    },
]
```

---

## Step 6 — Report

**Source:** `src/pipeline/step6_report.py`, `src/report.py`

**Purpose:** Generate the final deliverables from the accumulated pipeline results.

### Process

1. **`build_report_data()`** — assembles a canonical Python dict from all step results (profiles, validations, comparisons, file inventories, match rates, chart data series).
2. **Write `report_data.json`** — the presentation-agnostic data layer (292 KB). Any frontend can consume this.
3. **Render HTML** — Jinja2 template + embedded chart data JSON → self-contained HTML file with client-side Plotly charts.
4. **Export CSVs** — raw diff tables dumped for external analysis.

### Data/Presentation Separation

```
build_report_data()  →  report_data.json     ← canonical data artifact
                     →  comparison_report.html ← presentation layer 1 (Plotly + Jinja2)
                     →  React diff viewer      ← presentation layer 2 (reads JSON)
                     →  CLI / PDF / API        ← presentation layer N (future)
```

### Chart Data Series in JSON

| Key | Contents | Chart Type |
|-----|----------|------------|
| `chart_data.yoy_beneficiaries` | `[{year, count}, ...]` | Bar chart |
| `chart_data.yoy_claims` | `[{year, count}, ...]` | Bar chart |
| `chart_data.financial_trends` | `[{year, inpatient, outpatient, carrier}, ...]` | Grouped bar |
| `chart_data.financial_distribution` | `{medicare_reimb: [...], beneficiary_resp: [...], ...}` | Box plots |
| `chart_data.chronic_conditions` | `{years: [...], conditions: [{condition, rates}, ...]}` | Multi-line |

---

## Data Model

### DuckDB Tables (in-memory)

| Table | Source | Rows | Key Columns | Purpose |
|-------|--------|------|-------------|---------|
| `beneficiary_summary` | Old system (3 yearly CSVs) | 343,644 | `DESYNPUF_ID`, `summary_year` | Beneficiary demographics, coverage, chronic conditions, financials |
| `carrier_claims` | Old system (2 CSVs) | 4,741,335 | `CLM_ID` | Carrier claims with 13 line items each (diagnoses, procedures, payments) |
| `new_beneficiary_summary` | New system | 343,644 | `DESYNPUF_ID`, `summary_year` | Same schema as old, for comparison |
| `new_carrier_claims` | New system | 4,746,112 | `CLM_ID` | Same schema as old, for comparison |
| `_match_beneficiary` | Step 4 | 343,803 | `DESYNPUF_ID`, `summary_year` | Match classification (matched/old_only/new_only) |
| `_match_claims` | Step 4 | 4,746,112 | `CLM_ID` | Match classification |
| `_discrepancy_detail` | Step 5 | 343,485 | `DESYNPUF_ID` | Row-level field diffs for matched beneficiaries |
| `_financial_recon` | Step 4 | 262,017 | `DESYNPUF_ID`, `summary_year` | Carrier reimbursement: reported vs computed from claim lines |

---

## Comparison Checks Reference

These 110 checks run in Step 5 when new system data is available. They compare **old vs new** across two table pairs. Each is a function in `src/compare.py` that returns a `ComparisonResult`.

### Schema Checks (3 per table pair × 2 pairs = 6)

| Check Name | Description |
|-----------|-------------|
| `missing_columns_in_new` | Columns present in old system but absent in new |
| `extra_columns_in_new` | Columns present in new system but absent in old |
| `type_mismatches` | Columns with different DuckDB data types between systems |

### Row-Level Checks (3 per table pair × 2 pairs = 6)

| Check Name | Description |
|-----------|-------------|
| `row_count_difference` | Absolute difference in total row counts |
| `keys_missing_in_new` | Distinct key values in old but not in new (data loss) |
| `keys_extra_in_new` | Distinct key values in new but not in old (phantom records) |

### Field-Level Checks (22 beneficiary + 44 claims = 66)

For each column listed in `compare_cols`, runs:
```sql
SELECT COUNT(*) AS matched_rows,
       SUM(CASE WHEN old.col::VARCHAR IS DISTINCT FROM new.col::VARCHAR
           THEN 1 ELSE 0 END) AS mismatches
FROM old_table INNER JOIN new_table ON key = key
```

**Beneficiary columns compared (22):**

| Column | Category | What It Represents |
|--------|----------|--------------------|
| `BENE_ESRD_IND` | Clinical | End-stage renal disease indicator |
| `SP_STATE_CODE` | Geographic | State SSA code |
| `BENE_COUNTY_CD` | Geographic | County SSA code |
| `BENE_HI_CVRAGE_TOT_MONS` | Coverage | Part A coverage months |
| `BENE_SMI_CVRAGE_TOT_MONS` | Coverage | Part B coverage months |
| `BENE_HMO_CVRAGE_TOT_MONS` | Coverage | HMO coverage months |
| `PLAN_CVRG_MOS_NUM` | Coverage | Part D coverage months |
| `BENE_BIRTH_DT` | Demographic | Date of birth |
| `BENE_DEATH_DT` | Demographic | Date of death |
| `BENE_SEX_IDENT_CD` | Demographic | Sex code |
| `BENE_RACE_CD` | Demographic | Race code |
| `SP_ALZHDMTA` | Clinical | Alzheimer's/dementia flag |
| `SP_CHF` | Clinical | Congestive heart failure flag |
| `SP_CHRNKIDN` | Clinical | Chronic kidney disease flag |
| `SP_CNCR` | Clinical | Cancer flag |
| `SP_COPD` | Clinical | COPD flag |
| `SP_DEPRESSN` | Clinical | Depression flag |
| `SP_DIABETES` | Clinical | Diabetes flag |
| `SP_ISCHMCHT` | Clinical | Ischemic heart disease flag |
| `SP_OSTEOPRS` | Clinical | Osteoporosis flag |
| `SP_RA_OA` | Clinical | Rheumatoid arthritis / osteoarthritis flag |
| `SP_STRKETIA` | Clinical | Stroke / TIA flag |

**Carrier claims columns compared (44):**

| Column | Category | What It Represents |
|--------|----------|--------------------|
| `DESYNPUF_ID` | Identity | Beneficiary identifier |
| `CLM_FROM_DT` | Temporal | Claim start date |
| `CLM_THRU_DT` | Temporal | Claim end date |
| `ICD9_DGNS_CD_1`–`_8` | Clinical | 8 diagnosis codes per claim |
| `HCPCS_CD_1`–`_13` | Clinical | 13 procedure codes per claim line |
| `PRF_PHYSN_NPI_1`–`_5` | Provider | 5 performing physician NPIs |
| `TAX_NUM_1`–`_5` | Provider | 5 provider tax numbers |
| `LINE_PRCSG_IND_CD_1`–`_5` | Processing | 5 line processing indicators |
| `LINE_ICD9_DGNS_CD_1`–`_5` | Clinical | 5 line-level diagnosis codes |

### Aggregate Checks (9 beneficiary + 23 claims = 32)

For each column listed in `numeric_cols`, compares `SUM()` and `AVG()` between old and new tables. The `metric_value` is the absolute difference in sums.

**Beneficiary numeric columns (9):**

| Column | What It Represents |
|--------|--------------------|
| `MEDREIMB_IP` | Medicare reimbursement — inpatient |
| `BENRES_IP` | Beneficiary responsibility — inpatient |
| `PPPYMT_IP` | Primary payer payment — inpatient |
| `MEDREIMB_OP` | Medicare reimbursement — outpatient |
| `BENRES_OP` | Beneficiary responsibility — outpatient |
| `PPPYMT_OP` | Primary payer payment — outpatient |
| `MEDREIMB_CAR` | Medicare reimbursement — carrier |
| `BENRES_CAR` | Beneficiary responsibility — carrier |
| `PPPYMT_CAR` | Primary payer payment — carrier |

**Carrier claims numeric columns (23):**

| Column | What It Represents |
|--------|--------------------|
| `LINE_NCH_PMT_AMT_1`–`_5` | Payment amounts for lines 1–5 |
| `LINE_BENE_PTB_DDCTBL_AMT_1`–`_5` | Beneficiary deductibles for lines 1–5 |
| `LINE_BENE_PRMRY_PYR_PD_AMT_1`–`_3` | Primary payer payments for lines 1–3 |
| `LINE_COINSRNC_AMT_1`–`_5` | Coinsurance amounts for lines 1–5 |
| `LINE_ALOWD_CHRG_AMT_1`–`_5` | Allowed charges for lines 1–5 |

### Result Dataclass

```python
@dataclass
class ComparisonResult:
    check_name: str       # e.g. "field_mismatch_bene_birth_dt"
    category: str         # schema | row_level | field_level | aggregate
    table_pair: str       # e.g. "beneficiary_summary vs new_beneficiary_summary"
    description: str      # human-readable
    metric_value: float   # the primary metric (count, dollar diff, etc.)
    details: list[dict]   # optional context (old_sum, new_sum, etc.)
```

---

## Output Artifacts

### Report Files

| File | Description |
|------|-------------|
| `reports/report_data.json` | Canonical data artifact — all pipeline results as structured JSON (~293 KB) |
| `reports/comparison_report.html` | Interactive HTML report with Plotly charts, sidebar nav, sortable tables (~1.5 MB) |

### Data Exports (CSV — human-readable, Excel-compatible)

| File | Description |
|------|-------------|
| `reports/exports/_discrepancy_detail.csv` | Row-level field diffs for all matched beneficiary records |
| `reports/exports/_financial_recon.csv` | Per-beneficiary financial reconciliation (reported vs computed) |
| `reports/exports/_match_beneficiary.csv` | Match classification for every beneficiary record |
| `reports/exports/_match_claims.csv` | Match classification for every carrier claim record |

### Data Exports (Parquet — columnar, compressed, standard interchange)

| File | Description |
|------|-------------|
| `reports/exports/_discrepancy_detail.parquet` | Same data as CSV, in ZSTD-compressed Parquet format |
| `reports/exports/_financial_recon.parquet` | Same data as CSV, in ZSTD-compressed Parquet format |
| `reports/exports/_match_beneficiary.parquet` | Same data as CSV, in ZSTD-compressed Parquet format |
| `reports/exports/_match_claims.parquet` | Same data as CSV, in ZSTD-compressed Parquet format |

Parquet files are produced natively by DuckDB (no pyarrow dependency) and can be consumed by Spark, Pandas, Polars, BigQuery, Snowflake, or any tool that reads columnar data. ZSTD compression typically achieves 5–10× size reduction vs CSV.

### Persistent Datastore

| File | Description |
|------|-------------|
| `data/database/cms_claims.duckdb` | Persistent DuckDB database with all 8 tables — queryable via CLI, Python, or any DuckDB binding |

---

## Adding a New Check

To add a validation check:

1. Write a function in `src/validate.py` that takes a DuckDB connection and returns `list[ValidationResult]`.
2. Add a call to it in `validate.run()`.
3. The report will automatically pick it up — no template changes needed.

To add a comparison check:

1. Add columns to `compare_cols` or `numeric_cols` in the `TABLE_PAIRS` config in `src/compare.py`.
2. Or write a new comparison function and call it from `compare.run()`.
3. The report will automatically pick it up.
