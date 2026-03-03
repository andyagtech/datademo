# Solution Architecture

## Problem Statement

Compare outputs from two healthcare claims processing systems — an old (legacy CMS) system and a new replacement — to surface, quantify, and communicate discrepancies. The new system's data intentionally contains issues; the goal is to find them, measure their impact, and identify patterns.

## Design Decisions

### Why DuckDB?

The input data is large (2.4 GB of carrier claims CSVs, ~5M rows x 142 columns). The workload is analytical: scans, aggregations, joins. DuckDB is purpose-built for this:

- **Zero infrastructure.** No server, no configuration. A single `pip install` and a file on disk.
- **Native CSV scanning.** Reads CSVs directly without a separate ETL step. Handles type inference, null detection, and parallel reads out of the box.
- **Columnar engine.** Aggregations over 142-column tables are fast because it only reads the columns touched by each query.
- **Embeddable.** Runs inside the Python process — no network hops, no connection pooling, no Docker-in-Docker complexity.
- **Portable.** The `.duckdb` file can be copied to another machine and queried with the DuckDB CLI or any language binding.

Alternatives considered:
- **SQLite** — row-oriented, poor at analytical aggregations on wide tables.
- **PostgreSQL** — requires a running server; overkill for a batch pipeline.
- **Spark** — heavy setup for data that fits on a single machine.
- **Pandas-only** — 2.4 GB of CSVs in memory is feasible but fragile; SQL is clearer for complex joins and aggregations.

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
- **Reproducibility.** `python:3.14-slim` pins the latest stable Python release (October 2025). All dependencies — including DuckDB's compiled C extensions — ship binary wheels for 3.14. The image runs identically on macOS, Linux, and Windows (via Docker Desktop).
- **Data stays outside.** CSVs and the DuckDB file are volume-mounted, not baked into the image. This keeps the image small and the data portable.

### Report Design

The HTML report is designed to communicate findings, not just display data:

1. **Executive summary first.** Key metrics (total beneficiaries, claims, failed checks) and a red callout box listing every failed validation with issue counts.
2. **Interactive tables.** Every table has sortable columns (click any header). Sort handles numbers, percentages, and text.
3. **Collapsible sections.** Data profiles (which can be hundreds of rows for the 142-column carrier claims table) are collapsed by default. The header shows row/column counts and high-null warnings without needing to expand.
4. **Charts before tables.** Plotly charts for year-over-year trends, financial distributions, and chronic condition prevalence give a visual overview before the drill-down tables.

### Record Matching Strategy

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

## Testing

54 tests covering:

- **Unit tests** for each original module (profile, validate, compare, report)
- **Pipeline step tests** for receive, schema validate, and record matching
- **Integration tests** using in-memory DuckDB with synthetic sample data
- All tests run in <5 seconds with no external dependencies

```bash
pytest tests/ -v
```