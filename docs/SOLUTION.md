# Solution Architecture

## Problem Statement

Compare outputs from two healthcare claims processing systems — an old (legacy CMS) system and a new replacement — to surface, quantify, and communicate discrepancies. The new system's data intentionally contains issues; the goal is to find them, measure their impact, and identify patterns.

## Design Decisions

### Why DuckDB?

The input data is large (2.4 GB of carrier claims CSVs, ~5M rows × 142 columns). The workload is analytical: scans, aggregations, joins. DuckDB is purpose-built for this:

- **Zero infrastructure.** No server, no configuration. A single `pip install` and a file on disk. This is critical for a pipeline that needs to run in Docker, on a developer laptop, or inside an AWS Lambda function without provisioning a database server.
- **Native CSV/Parquet I/O.** Reads CSVs directly with type inference, null detection, and parallel reads. Exports to Parquet natively — no pandas or pyarrow dependency needed for columnar output.
- **Columnar engine.** Aggregations over 142-column tables are fast because DuckDB only reads the columns touched by each query. Our carrier claims table has 142 columns but most queries touch fewer than 10 — a columnar engine avoids reading the other 132.
- **Embeddable.** Runs inside the Python process — no network hops, no connection pooling, no Docker-in-Docker complexity. The entire database is a single file.
- **Portable.** The `.duckdb` file can be copied to another machine and queried with the DuckDB CLI, Python, R, Node.js, or any of DuckDB's 15+ language bindings.

**Maturity and adoption:** DuckDB reached **v1.0 in June 2024**, marking a stable API and storage format guarantee. It is developed by DuckDB Labs, a company spun out of CWI Amsterdam (the same research institute that created MonetDB). DuckDB has 25K+ GitHub stars, is used in production by organizations including Google, MotherDuck (cloud DuckDB), and dbt Labs, and ships as a core component of tools like Evidence, Observable, and DBeaver. For this assessment, we use DuckDB ≥1.1.0 — a stable, production-grade release.

**Why not the alternatives:**
- **SQLite** — row-oriented storage engine, designed for OLTP (small reads/writes). Analytical aggregations on wide tables are 10-50× slower than DuckDB because SQLite reads entire rows even when a query only needs 2 columns.
- **PostgreSQL** — excellent database, but requires a running server process, connection management, and configuration. For a self-contained batch pipeline that runs in Docker or Lambda, this is unnecessary complexity.
- **Spark** — designed for distributed computing across clusters. Our data fits on a single machine (2.4 GB). Spark's JVM startup, driver/executor model, and configuration overhead add minutes of latency and gigabytes of dependencies for no benefit at this scale.
- **Pandas-only** — 2.4 GB of CSVs in memory is feasible but fragile. SQL is clearer than chained DataFrame operations for the complex multi-table joins and aggregations in our comparison logic (FULL OUTER JOIN with 24 diff columns, financial reconciliation with GROUP BY + HAVING). Pandas also lacks native Parquet export without pyarrow.

### Why a 6-Step Pipeline?

The original flat pipeline (ingest -> profile -> validate -> compare -> report) worked but had no fault isolation. If someone uploaded a CSV with wrong headers, it would fail deep inside the ingest step with an opaque DuckDB error.

The 6-step design adds:

1. **Early rejection.** Steps 1-2 (Receive, Schema Validate) catch bad input before any expensive processing. A malformed CSV is rejected in <1 second instead of after a 30-second ingest.
2. **Gate logic.** Each step can halt the pipeline with a clear error message. The pipeline context carries a `halted` flag and `halt_reason`.
3. **Separation of concerns.** File I/O (Step 1) is separate from validation logic (Step 2), which is separate from database operations (Step 3). This makes each step independently testable and replaceable.
4. **Cloud readiness.** Each step is a pure function: `run(ctx) -> StepResult`. Locally, the runner calls them in sequence. In the cloud, each step becomes a Lambda function, and Step Functions handles orchestration. The same Python code runs in both contexts.

### Why Docker?

The pipeline has minimal dependencies (Python + 4 pip packages), but:

- **DuckDB versions matter.** Database files are not guaranteed compatible across major versions.
- **Python version matters.** We use type unions (`int | str`) and other 3.10+ features.
- **Reproducibility.** `python:3.14-slim` pins the current stable Python release (October 2025). All dependencies — including DuckDB's compiled C extensions — ship binary wheels for 3.14. The image runs identically on macOS, Linux, and Windows (via Docker Desktop).
- **Data stays outside.** CSVs and the DuckDB file are volume-mounted, not baked into the image. This keeps the image small and the data portable.

### Report Design

The HTML report is designed to communicate findings, not just display data:

1. **Executive summary first.** Key metrics (total beneficiaries, claims, failed checks) and a red callout box listing every failed validation with issue counts.
2. **Interactive tables.** Every table has sortable columns (click any header). Sort handles numbers, percentages, and text.
3. **Collapsible sections.** Data profiles (which can be hundreds of rows for the 142-column carrier claims table) are collapsed by default. The header shows row/column counts and high-null warnings without needing to expand.
4. **Charts before tables.** Plotly charts for year-over-year trends, financial distributions, and chronic condition prevalence give a visual overview before the drill-down tables.

### Match & Validate Strategy

When new system data is available, Step 4 performs a FULL OUTER JOIN:

- **Beneficiaries:** matched on `(DESYNPUF_ID, summary_year)` — composite key because the same beneficiary appears once per year.
- **Claims:** matched on `CLM_ID` — unique claim identifier.

Every record is classified as:
- `matched` — exists in both systems (proceed to field-level comparison)
- `old_only` — exists in old system but missing from new (data loss)
- `new_only` — exists in new system but not in old (phantom records)

Step 5 then runs field-by-field diffs on matched records and classifies discrepancies by type (financial, demographic, clinical, temporal) with dollar impact calculations.

## Deployment Strategy

### Local (current)

```
python -m src.main [--new-data PATH] [--skip-ingest] [--db-path PATH]
```

Or via Docker:

```
docker build -t cms-pipeline .
docker run --rm -v $(pwd)/data:/app/data -v $(pwd)/reports:/app/reports cms-pipeline
```

### Cloud (AWS — implemented)

Deployed using AWS SAM (`infra/template.yaml`):

```
API Gateway POST /pipeline/start
  │
  ▼
Step Functions state machine (infra/statemachine.asl.json)
  │
  ├─ Lambda: Step 1 (Receive)       ── S3 file listing + checksums
  ├─ Gate check ─────────────────── halted? → Fail
  ├─ Lambda: Step 2 (Schema)        ── S3 CSV header reads
  ├─ Gate check
  ├─ Lambda: Step 3 (Ingest)        ── DuckDB in /tmp, reads CSVs from S3 via httpfs
  │                                    10 GB memory, 15 min timeout
  │                                    snapshots DuckDB file → S3
  ├─ Gate check
  ├─ Lambda: Step 4 (Match)         ── restores DuckDB from S3, matches records
  ├─ Lambda: Step 5 (Compare)       ── field-level diffs, trend analysis
  ├─ Lambda: Step 6 (Report)        ── generates HTML, uploads to S3
  │                                    returns presigned download URL
  ▼
  Success / Fail
```

**Key design decisions:**

- **Lambda container images** (not zip deploys) — based on the AWS Lambda Python base image, shared with the local Dockerfile. Avoids the 250 MB zip limit and ensures identical Python + DuckDB versions.
- **DuckDB on Lambda** — runs in `/tmp` (10 GB ephemeral storage). Between Lambda invocations, the DuckDB file is snapshotted to S3 and restored by the next step. This works because our dataset (~2.5 GB) fits in Lambda's 10 GB memory limit.
- **DuckDB httpfs extension** — reads CSVs directly from S3 during ingest, eliminating the need to download multi-GB files to `/tmp`.
- **StorageAdapter pattern** — `src/adapters/aws.py` (S3Storage) implements the same `StorageAdapter` protocol as `src/adapters/local.py` (LocalStorage). Pipeline steps use `ctx.storage` for I/O without knowing which backend they're on.
- **Step Functions gate logic** — mirrors `runner.py`'s halt checks. After each Lambda step, a Choice state checks `$.halted` and routes to a Fail state if true.

**Scaling note:** For datasets >5 GB, the heavy steps (ingest, compare) can be moved to **Fargate** using the same container image. The SAM template would add an ECS task definition alongside the Lambda functions.

## Analysis Findings

### Summary

The new system achieves **99.87% record-level accuracy** on beneficiary data (446 mismatched records out of 343,485 matched). Financial divergence totals **$35,624.71** on $1.24B in total reimbursements (0.003%). While the aggregate impact is small, the patterns reveal two distinct systematic bugs.

### Finding 1: Date Migration Bug (BENE_BIRTH_DT)

**178 beneficiary records** have different birth dates between systems — 34.2% of all field-level discrepancies, making it the single largest source of error. The count is stable across years (63 in 2008, 63 in 2009, 52 in 2010), indicating a systematic parsing or migration issue rather than random corruption.

**Root cause hypothesis:** The new system likely has a date parsing bug that affects a specific date format or range. The consistency across years rules out a time-dependent regression.

**Impact:** Demographic — no direct financial impact, but incorrect birth dates could affect age-based eligibility calculations downstream.

### Finding 2: Payment Calculation Bias

All 9 financial reimbursement columns show mismatches, and **every dollar delta is positive** (net = abs = $35,624.71). The new system consistently **overstates** reimbursement amounts — it never understates them. This one-directional pattern is a strong indicator of a systematic calculation bias, not random noise.

Breakdown by service type:

| Service Type | Divergence | Affected Records |
|---|---|---|
| Outpatient (OP) | $14,339.20 | 31–47 per column |
| Inpatient (IP) | $12,363.99 | 32–38 per column |
| Carrier (CAR) | $8,921.52 | 30–46 per column |

**Root cause hypothesis:** The new system may be applying a rounding rule, fee schedule adjustment, or filter condition differently than the old system, causing small per-record overpayments that aggregate across affected records.

### Finding 3: Phantom Claims

The new system contains **4,777 carrier claims** that have no corresponding record in the old system. Zero claims are lost in the other direction (old-only = 0). This asymmetry suggests the new system is generating spurious claim records — possibly from a join expansion, duplicate processing, or an off-by-one error in batch boundaries.

### Finding 4: Claims Payment Column Concentration

On matched claims, **10,411** have mismatched `LINE_NCH_PMT_AMT_1` (primary payment amount) — roughly **5x more** than the next most-affected payment column (`LINE_ALOWD_CHRG_AMT_1` at 657). This concentration in a single column points to a targeted bug in the primary payment calculation logic rather than a broad data corruption issue.

### Geographic Distribution

Discrepancies are spread across **50 of 52 state codes** with no dramatic geographic concentration. The highest mismatch rate is State 02 (0.42%, 3 records) — statistically insignificant given the small sample. This confirms the issues are systemic (code-level) rather than geographic (data-level).

### Trend Analysis

Discrepancy rates are **stable across the three summary years** (2008: 0.12%, 2009: 0.14%, 2010: 0.12%). The slight 2009 uptick is within normal variance. This stability suggests the bugs are inherent to the migration/calculation logic and do not worsen with time or data volume.

### Recommendation

The new system is **not ready for production cutover**. While overall accuracy is high (99.87%), two systematic bugs should be fixed:

1. **Date handling** — investigate BENE_BIRTH_DT parsing logic in the new system's beneficiary ingestion pipeline.
2. **Payment calculation** — investigate the one-directional overpayment bias, particularly in LINE_NCH_PMT_AMT calculation. The 5x concentration in this column narrows the search area.

After fixes, re-run this pipeline to verify the discrepancy rate drops to zero or near-zero.

## Testing

264 tests covering:

- **231 unit/integration tests** using synthetic data (in-memory DuckDB + temp files) — no real data needed. Includes functional programming primitives, property-based tests (Hypothesis), pattern matching, and Z-set algebra.
- **33 real-data validation tests** — verify actual CMS files (row counts, schemas, data quality, cross-system consistency). Auto-skipped if data is not present.
- **Unit tests** for each core module (profile, validate, compare, report)
- **Pipeline step tests** for receive, schema validate, and record matching
- **Integration tests** for end-to-end report generation

```bash
pytest tests/ -v
```