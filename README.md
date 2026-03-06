# CMS Claims Comparison Pipeline

A data comparison and validation tool that compares outcomes from two healthcare claims processing systems. Given a legacy system's output (CMS DE-SynPUF Medicare data) and a replacement system's output, the pipeline ingests both, validates data quality, matches records, quantifies discrepancies, and generates an interactive report.

Built for the USDS Data Engineering Take-Home Assessment.

| | |
|---|---|
| **Repository** | [github.com/andyagtech/cmsdata-assessment](https://github.com/andyagtech/cmsdata-assessment) |
| **Hosted Report** | [ddmmvtx76d1f8.cloudfront.net](https://ddmmvtx76d1f8.cloudfront.net/reports/comparison_report.html) |
| **Full Bundle Download** | [cmsdata-assessment_full.zip](https://andy-barr-cmsdata-assessment.s3.us-west-2.amazonaws.com/downloads/cmsdata-assessment_full.zip) |

---

## Prerequisites

| Approach | What you need |
|----------|---------------|
| **Docker (recommended)** | [Docker Desktop](https://www.docker.com/products/docker-desktop/) — nothing else required |
| **Local Python** | Python 3.14+ and `pip install -r requirements.txt` |

All Python libraries (DuckDB, Pandas, Plotly, Jinja2, pytest) are listed in `requirements.txt` — there are **no system-level dependencies** beyond Python itself.

---

## Quick Start

### Option A: Docker (recommended)

Docker is the simplest way to run the pipeline on any machine. No Python install required.

```bash
# 1. Build the image
docker build -t cms-pipeline .

# 2. Place ZIP archives in data/original_downloads/  (see "Data Setup" below)
#    If new system CSVs are in data/new_system/, they are auto-detected.

# 3. Run everything
docker run --rm -p 8888:8888 \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/reports:/app/reports" \
  cms-pipeline

# 4. Open http://localhost:8888
```

That's it. The entrypoint automatically:
1. Extracts ZIPs → runs the 6-step pipeline → writes report
2. Runs the test suite
3. Renders markdown docs as styled HTML
4. Starts a documentation web server on port 8888

Reports are also saved to `reports/comparison_report.html` for standalone viewing.

<details>
<summary><strong>Advanced Docker options</strong></summary>

```bash
# Pipeline-only (no web server, no tests)
docker run --rm \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/reports:/app/reports" \
  cms-pipeline python -m src.main

# Skip ingest on re-runs (reuses existing DuckDB)
docker run --rm -p 8888:8888 \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/reports:/app/reports" \
  cms-pipeline ./entrypoint.sh --skip-ingest

# Skip tests (faster re-runs)
docker run --rm -p 8888:8888 \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/reports:/app/reports" \
  cms-pipeline ./entrypoint.sh --skip-tests
```

> **Note:** Overriding the command (e.g., `python -m src.main`) replaces the entire entrypoint —
> tests, doc rendering, and the web server will **not** run. To customize pipeline arguments while
> keeping the full entrypoint, pass them after `./entrypoint.sh`.

</details>

### Option B: Local Python

```bash
# Requires Python 3.14+
# Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Download and place data (see "Data Setup" below)

# Run the pipeline
python -m src.main

# With new system data
python -m src.main --new-data data/new_system/

# Skip ingest on re-runs
python -m src.main --skip-ingest

# Run tests
pytest tests/ -v
```

<details>
<summary><strong>Alternative: using <code>uv</code> (faster)</strong></summary>

[uv](https://docs.astral.sh/uv/) is a fast Python package manager. If you have it installed:

```bash
uv venv --python 3.14
source .venv/bin/activate
uv pip install -r requirements.txt
```

</details>

### Viewing Reports & Documentation

The interactive report, documentation hub, and browser tools (Schema Explorer, SQL Explorer, Parquet Viewer) require an HTTP server — they will not fully work over `file://` due to browser security restrictions.

```bash
# Start a local server (Python built-in, no extra dependencies)
./scripts/serve.sh            # http://localhost:8888
./scripts/serve.sh 9000       # custom port
```

Then open:
- **Report:** http://localhost:8888/reports/comparison_report.html
- **Documentation:** http://localhost:8888/docs/index.html

### Web UI (Drag-and-Drop)

For a browser-based experience with file uploads:

```bash
python -m uvicorn web.server:app --host 0.0.0.0 --port 8000
# Open http://localhost:8000
```

Upload old system CSVs → optionally upload new system CSVs → run pipeline → view report. The web UI supports drag-and-drop, streams pipeline progress in real time, and serves the generated report directly.

### Data Setup

The pipeline needs **5 old system CSV files** (required) and optionally **new system CSV files** for comparison. You can provide them as ZIP archives or pre-extracted CSVs.

#### Old System Data (required)

Download **Sample 1** from [CMS DE-SynPUF](https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-claims-synthetic-public-use-files/cms-2008-2010-data-entrepreneurs-synthetic-public-use-file-de-synpuf/de10-sample-1):

| Download link on CMS site | Extracted CSV filename |
|---------------------------|----------------------|
| DE1.0 Sample 1 2008 Beneficiary Summary File | `DE1_0_2008_Beneficiary_Summary_File_Sample_1.csv` |
| DE1.0 Sample 1 2009 Beneficiary Summary File | `DE1_0_2009_Beneficiary_Summary_File_Sample_1.csv` |
| DE1.0 Sample 1 2010 Beneficiary Summary File | `DE1_0_2010_Beneficiary_Summary_File_Sample_1.csv` |
| DE1.0 Sample 1 Carrier Claims A | `DE1_0_2008_to_2010_Carrier_Claims_Sample_1A.csv` |
| DE1.0 Sample 1 Carrier Claims B | `DE1_0_2008_to_2010_Carrier_Claims_Sample_1B.csv` |

**Option 1 — Place ZIP archives (auto-extracted):**
```bash
mv *.zip data/original_downloads/
```
The pipeline **automatically extracts** ZIPs into `data/old_system/` during Step 1. No manual unzipping required.

**Option 2 — Place pre-extracted CSVs directly:**
```bash
mv *.csv data/old_system/
```
If CSVs are already in `data/old_system/`, the pipeline skips extraction and uses them directly.

#### New System Data (optional — for comparison)

Place the new system CSVs into `data/new_system/`:
```bash
# If you have a ZIP:
unzip "New Claims System Outputs.zip" -d data/new_system/

# Or if you have CSVs:
mv *_NEWSYSTEM.csv data/new_system/
```
The entrypoint **auto-detects** CSVs in `data/new_system/` — no extra flags needed. New system files are matched by header content (files containing `Beneficiary` or `Carrier` column patterns), not by filename.

#### Expected folder structure after setup

```
data/
├── original_downloads/      # Option 1: place ZIPs here (auto-extracted)
│   ├── README.md             # Detailed file listing (tracked in git)
│   └── *.zip
├── old_system/               # CSVs end up here (5 files)
│   ├── DE1_0_2008_Beneficiary_Summary_File_Sample_1.csv
│   ├── DE1_0_2009_Beneficiary_Summary_File_Sample_1.csv
│   ├── DE1_0_2010_Beneficiary_Summary_File_Sample_1.csv
│   ├── DE1_0_2008_to_2010_Carrier_Claims_Sample_1A.csv
│   └── DE1_0_2008_to_2010_Carrier_Claims_Sample_1B.csv
├── new_system/               # Optional: new system CSVs for comparison
│   └── *.csv
└── database/                 # Auto-generated by pipeline
    └── cms_claims.duckdb
```

**Data lineage:**
```
data/original_downloads/*.zip  →  Step 1: auto-extract  →  data/old_system/*.csv
                                                                    ↓
data/new_system/*.csv  ─────────────────────────────────→  Step 3: Ingest  →  data/database/cms_claims.duckdb
```

---

## Components

### What You Need

| Component | Purpose | Required? |
|-----------|---------|-----------|
| **Python 3.14+** | Runtime | Yes (or use Docker) |
| **DuckDB** | Analytical database — zero-config, embedded, handles GBs of CSVs natively | Yes (pip install) |
| **Pandas** | DataFrame conversion for chart building | Yes (pip install) |
| **Plotly** | Interactive charts in the HTML report | Yes (pip install) |
| **Jinja2** | HTML report templating | Yes (pip install) |
| **Markdown** | Renders .md docs as styled HTML pages | Yes (pip install) |
| **pytest** | Test runner | Dev only |
| **Docker** | Portable containerized execution | Recommended |

All Python dependencies are in `requirements.txt`. There are **no system-level dependencies** beyond Python itself — DuckDB is a pure pip install with no external database server.

### Python Version

The Dockerfile pins `python:3.14-slim`. The codebase requires Python 3.10+ (for `X | Y` union types and `dict[str, ...]` generics). Python 3.14 is the current stable release (October 2025) with full binary wheel support across all dependencies.

### Python Libraries

| Library | Version | Why We Use It |
|---------|---------|---------------|
| **duckdb** | ≥1.1.0 | Embedded analytical database. Reads CSVs natively, runs columnar SQL, handles 5M-row tables without a server. The core of our ETL and query engine. |
| **pandas** | ≥2.0.0 | Used only for chart data — `fetchdf()` converts DuckDB results to DataFrames for Plotly. Not used for heavy data processing (DuckDB handles that). |
| **plotly** | ≥5.18.0 | Generates interactive HTML charts (bar, box, scatter). Charts are embedded directly in the report as self-contained HTML — no server needed. |
| **jinja2** | ≥3.1.0 | HTML report templating. The report template is a single Jinja2 string with loops, conditionals, and variable interpolation. |
| **pytest** | ≥8.0.0 | Test runner. Dev dependency only — not needed to run the pipeline. |
| **fastapi** | ≥0.110.0 | Web upload UI (`web/server.py`). Optional — install via `pip install -r requirements-web.txt`. |
| **uvicorn** | ≥0.27.0 | ASGI server for FastAPI. Optional — same as above. |

### What You Provide

> **Detailed reference:** See [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md) for full column definitions, table schemas, and instructions for using other CMS samples.

| Input | Where to put it | Format |
|-------|----------------|--------|
| **Old system data** (required) | ZIPs → `data/original_downloads/` **or** CSVs → `data/old_system/` | 5 files: 3 beneficiary summary (2008-2010) + 2 carrier claims |
| **New system data** (optional) | CSVs → `data/new_system/` | CSVs with beneficiary/carrier column headers |

See [Data Setup](#data-setup) above for download links and step-by-step instructions. The pipeline auto-detects file types by reading CSV headers — it doesn't rely on filenames.

### What You Get

| Output | Location | Description |
|--------|----------|-------------|
| **HTML Report** | `reports/comparison_report.html` | Interactive report with sidebar nav, Plotly charts, sortable tables |
| **JSON Data** | `reports/report_data.json` | Canonical data artifact — all metrics as structured JSON |
| **DuckDB Database** | `data/database/cms_claims.duckdb` | Persistent analytical database — query directly with DuckDB CLI |
| **CSV Exports** | `reports/exports/*.csv` | Raw analysis tables — human-readable, Excel-compatible |
| **Parquet Exports** | `reports/exports/*.parquet` | Same tables in ZSTD-compressed columnar format for downstream tools (Spark, Pandas, BigQuery) |

---

## Pipeline Architecture

```
┌─────────────────────────────────────────────────────────┐
│  1. RECEIVE        Accept files, verify integrity       │
│  ↓ SHA-256 checksums, zip extraction, file inventory    │
├─────────────────────────────────────────────────────────┤
│  2. SCHEMA VALIDATE   Gate check before ingestion       │
│  ↓ Header matching, type classification, early reject   │
├─────────────────────────────────────────────────────────┤
│  3. INGEST & PROFILE  Load into DuckDB, profile quality │
│  ↓ Null rates, distributions, anomaly detection         │
├─────────────────────────────────────────────────────────┤
│  4. MATCH & VALIDATE  Record matching + consistency checks│
│  ↓ FULL OUTER JOIN, classify: matched/old-only/new-only │
├─────────────────────────────────────────────────────────┤
│  5. COMPARE           Field-level diffs, trend analysis │
│  ↓ Discrepancy classification, dollar impact, by-year   │
├─────────────────────────────────────────────────────────┤
│  6. REPORT            Generate HTML + CSV exports       │
└─────────────────────────────────────────────────────────┘
```

**Gate logic:** Steps 1-2 can halt the pipeline before expensive processing if files are missing or schemas are invalid.

### Module Map

| Step | Pipeline Module | Core Module | Purpose |
|------|----------------|-------------|---------|
| 1 | `src/pipeline/step1_receive.py` | — | File intake, zip extraction, SHA-256 |
| 2 | `src/pipeline/step2_schema_validate.py` | — | CSV header validation, type classification |
| 3 | `src/pipeline/step3_ingest.py` | `src/ingest.py`, `src/profile.py` | DuckDB loading, column profiling, anomaly detection |
| 4 | `src/pipeline/step4_match.py` | `src/validate.py` | Record matching, internal consistency checks |
| 5 | `src/pipeline/step5_compare.py` | `src/compare.py` | Schema/row/field/aggregate comparison, trend analysis |
| 6 | `src/pipeline/step6_report.py` | `src/report.py` | HTML report generation, CSV export |

---

## Validation Checks

> **Detailed reference:** See [`docs/PIPELINE.md`](docs/PIPELINE.md) for the complete check-by-check breakdown with SQL logic, column definitions, and instructions for adding new checks.

### Internal Consistency (Old System)

| Category | Check | Description |
|----------|-------|-------------|
| **Identity** | Orphan claims | Beneficiary IDs in claims but not in summary |
| **Identity** | No-claims beneficiaries | Beneficiaries with zero carrier claims |
| **Identity** | Duplicate claim IDs | Claim IDs appearing more than once |
| **Temporal** | Claims after death | Claims with start date after beneficiary death |
| **Temporal** | Date inversion | Claims where start date > end date |
| **Demographic** | Sex/Race/DOB drift | Demographics changing across summary years |
| **Financial** | MEDREIMB_CAR recon | Summary reimbursement vs computed claim-line aggregates |
| **Financial** | BENRES_CAR recon | Summary beneficiary responsibility vs claim lines |
| **Financial** | PPPYMT_CAR recon | Summary primary payer vs claim lines |

### Cross-System Comparison (Old vs New)

| Category | Check | Description |
|----------|-------|-------------|
| **Schema** | Missing/extra columns | Columns in one system but not the other |
| **Schema** | Type mismatches | Same column, different data types |
| **Row-level** | Missing/extra records | Records by key in one system but not the other |
| **Field-level** | Value mismatches | Per-field diffs on matched records |
| **Aggregate** | Sum/mean divergence | Aggregate financial metrics comparison |
| **Trend** | By-year breakdown | Mismatch rates and dollar impact per year |

---

## CLI Reference (Local)

```
python -m src.main [OPTIONS]

Options:
  --new-data PATH    Path to directory or zip containing new system CSVs
  --skip-ingest      Skip ingestion, reuse existing DuckDB database
  --db-path PATH     Custom DuckDB database path (default: data/database/cms_claims.duckdb)
```

---

## Cloud Deployment (AWS)

The same pipeline logic runs on AWS using Lambda container images orchestrated by Step Functions. The documentation hub (including Parquet Viewer and SQL Explorer) is hosted as an S3 static website behind CloudFront.

> **Status:** The cloud deployment is **scaffolded but not production-tested**. See the [Implementation Status](#cloud-implementation-status) table below for details on what is implemented vs stubbed.

### Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │            S3 Static Website                │
  Browser ────────▶ │  docs/index.html, schema_explorer.html,    │
                    │  sql_explorer.html, parquet_viewer.html,    │
                    │  reports/comparison_report.html,            │
                    │  reports/exports/*.parquet                  │
                    └─────────────────────────────────────────────┘

  API Gateway POST /pipeline/start
          │
          ▼
    Step Functions state machine
          │
          ├─ Step 1: Lambda (Receive)       ── S3 file listing + checksums
          ├─ Gate check ──────────────────── halted? → Fail
          ├─ Step 2: Lambda (Schema)         ── S3 CSV header reads
          ├─ Gate check
          ├─ Step 3: Lambda (Ingest)         ── DuckDB in /tmp, reads from S3 via httpfs
          ├─ Gate check                        snapshot DuckDB → S3
          ├─ Step 4: Lambda (Match)          ── restore DuckDB from S3, match records
          ├─ Gate check                        snapshot → S3
          ├─ Step 5: Lambda (Compare)        ── restore, compare, snapshot → S3
          ├─ Gate check
          └─ Step 6: Lambda (Report)         ── generate HTML + Parquet exports → S3
                                                sync docs/ to S3 static site bucket
```

See also the [Architecture page](docs/architecture.html) for an interactive Mermaid diagram of the cloud deployment.

### AWS Services

| Service | Role |
|---------|------|
| **S3** | Stores input CSVs, DuckDB snapshots between steps, output reports, and hosts the static documentation site |
| **Lambda** | Runs each pipeline step as a container image (up to 10 GB memory, 15 min timeout) |
| **Step Functions** | Orchestrates the 6 steps with gate logic (mirrors `runner.py`) |
| **API Gateway** | HTTP POST trigger to start a pipeline run |
| **CloudFront** | CDN for the static documentation site (optional, for production) |
| **IAM** | Least-privilege roles for Lambda → S3 access |

### DuckDB on Lambda

DuckDB runs inside the Lambda container using `/tmp` (10 GB ephemeral storage) for the database file. Between Lambda invocations, the DuckDB file is snapshotted to S3 and restored by the next step. DuckDB's `httpfs` extension reads CSVs directly from S3 during ingest — no need to download multi-GB files to `/tmp`.

For datasets larger than ~5 GB, consider switching the heavy steps (ingest, compare) to **Fargate** (same container image, more memory/storage). The SAM template can be extended to support this.

### Prerequisites

- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) v1.100+
- Docker (for `sam build`)
- AWS CLI v2 configured with credentials

### Environment Variables & Credentials

**AWS credentials** — configure via any standard method:

```bash
# Option 1: Named profile (recommended)
aws configure --profile personal
# Then use: sam deploy --profile personal

# Option 2: Environment variables
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-east-1

# Option 3: IAM role (for CI/CD or EC2/ECS)
# Automatically picked up by the AWS SDK
```

**Lambda environment variables** (set automatically by the SAM template):

| Variable | Set By | Value |
|----------|--------|-------|
| `BUCKET_NAME` | SAM template | `!Ref DataBucket` — the S3 bucket name |
| `ENVIRONMENT` | SAM template | `dev`, `staging`, or `prod` |
| `STATE_MACHINE_ARN` | SAM template | ARN of the Step Functions state machine (start function only) |
| `DB_PATH` | Handler code | `/tmp/pipeline.duckdb` (Lambda ephemeral storage) |

**IAM permissions required** for the deploying user/role:

- `cloudformation:*` — SAM uses CloudFormation under the hood
- `s3:*` on the pipeline bucket
- `lambda:*` — create/update functions
- `states:*` — create/update Step Functions
- `apigateway:*` — create/update API Gateway
- `iam:CreateRole`, `iam:AttachRolePolicy`, `iam:PassRole` — Lambda execution roles
- `ecr:*` — push container images

### Deploy

```bash
cd infra/

# Build container images
sam build

# Deploy (first time — guided setup)
sam deploy --guided --profile personal

# Subsequent deploys
sam deploy --profile personal

# Upload data to S3
aws s3 cp data/original_downloads/ s3://<BUCKET>/original_downloads/ --recursive --profile personal
```

After the report step completes, the pipeline syncs `docs/` and `reports/` to the S3 static site bucket, making the documentation hub (including Parquet Viewer and SQL Explorer) accessible via the S3 website URL or CloudFront.

### Trigger a Pipeline Run

```bash
# Start the pipeline via API Gateway
curl -X POST https://<API_ENDPOINT>/dev/pipeline/start \
  -H "Content-Type: application/json" \
  -d '{"old_data_prefix": "raw"}'
```

The API endpoint URL is printed as a CloudFormation output after `sam deploy`.

### Teardown

To remove all AWS resources when you're done:

```bash
# Remove all deployed resources
scripts/teardown_cloud.sh

# Or manually:
cd infra/
sam delete --stack-name cms-claims-pipeline-dev --profile personal --no-prompts
# Then empty and delete the S3 bucket if needed
```

See `scripts/teardown_cloud.sh` for a complete cleanup script that empties S3 buckets and deletes the CloudFormation stack.

### Cloud Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| `src/pipeline/step1–6` | ✅ **Implemented** | Shared with local — same code runs in both modes |
| `src/adapters/aws.py` (S3Storage) | ✅ **Implemented** | S3 read/write/list/glob via boto3 |
| `cloud/handlers.py` (Lambda handlers) | ✅ **Implemented** | One handler per step + API trigger |
| `infra/template.yaml` (SAM template) | ✅ **Implemented** | S3, Lambda ×7, Step Functions, API Gateway |
| `infra/statemachine.asl.json` | ✅ **Implemented** | Full 6-step orchestration with gate logic, retries, error handling |
| S3 static site for docs | ✅ **Deployed** | All docs, reports, and interactive tools hosted on S3 |
| CloudFront CDN | ✅ **Deployed** | HTTPS distribution in front of S3 static site |
| Report Pal (AI Chat) | ✅ **Deployed** | Lambda + API Gateway for OpenAI-powered chat with DuckDB |
| Report Pal (Voice) | ✅ **Deployed** | WebRTC voice via OpenAI Realtime API |
| DuckDB S3 snapshotting | ⚠️ **Scaffolded** | Handler code has snapshot/restore logic; not tested with real S3 |
| End-to-end cloud test | ❌ **Not tested** | Pipeline handlers are coded but have not been deployed or run on real AWS |
| CI/CD pipeline | ❌ **Not implemented** | No GitHub Actions / CodePipeline defined |
| Monitoring / alarms | ❌ **Not implemented** | No CloudWatch alarms or dashboards |

### Shared Code

The local and cloud versions share all pipeline logic:

| Layer | Shared | Local-specific | Cloud-specific |
|-------|--------|----------------|----------------|
| `src/pipeline/step1–6` | ✅ | | |
| `src/*.py` (core modules) | ✅ | | |
| `src/adapters/__init__.py` (Protocol) | ✅ | | |
| `src/adapters/local.py` | | ✅ | |
| `src/adapters/aws.py` | | | ✅ |
| `src/pipeline/runner.py` | | ✅ (sequential) | |
| `cloud/handlers.py` | | | ✅ (Lambda entry points) |
| `infra/template.yaml` | | | ✅ (SAM infrastructure) |

---

## Report Pal (AI Chat Assistant)

Every page in the hosted report includes **Report Pal**, an AI assistant that helps reviewers explore findings through natural conversation — via text or voice.

### Text Mode

- Powered by **OpenAI GPT-4o** via a Lambda backend (`cloud/handlers.py`)
- Has live access to the **DuckDB database** via the `query_database` tool — it writes and executes SQL to answer data questions
- Pre-cached answers for common questions (instant response, no API call)
- Conversation persists across page navigations via `sessionStorage`
- SQL queries shown inline with copy-to-clipboard and double-click to open in SQL Explorer

### Voice Mode

- Powered by **OpenAI Realtime API** via WebRTC (same pattern as PurlPal)
- Full-duplex voice: speak naturally, AI responds with OpenAI's **coral** voice
- Server VAD for automatic turn detection — no push-to-talk needed
- Whisper-1 transcription — user's spoken words appear in the chat panel
- Stop button in header bar immediately cancels AI voice mid-sentence (`response.cancel`)
- Ephemeral tokens generated by a dedicated Lambda — no API keys reach the browser

### Architecture

```
Browser (chat-widget.js)
  ├── Text: POST → Chat Lambda (cloud/handlers.py) → OpenAI + DuckDB
  └── Voice: ephemeral token → WebRTC → OpenAI Realtime API (full-duplex audio)
```

### Security

- **No API keys in the frontend** — all OpenAI calls go through Lambda backends
- **Ephemeral tokens** for Realtime API expire after 60 seconds
- **OpenAI API key** stored in AWS SSM Parameter Store, fetched at runtime
- **CORS** configured on Lambda Function URLs to allow only the CloudFront origin
- No credentials are committed to the repository (verified via git history scan)

### Reviewer Bundle

The project can be bundled for reviewers **with the AI Assistant fully functional** on all pages, without shipping the proprietary Lambda backend source code.

```bash
# 1. Run the pipeline (generates report + cached answers)
python -m src.main

# 2. Re-render docs (picks up cached-answers.js template change)
python scripts/render_md_docs.py

# 3. Create the reviewer bundle
./scripts/bundle.sh --code-only
```

**What's included:** All source code, docs, report, tests, and `docs/cached-answers.js` (92 pre-built Q&A pairs covering all Bloom's Taxonomy levels).

**What's excluded:** `cloud/` (Lambda handlers), `infra/` (SAM templates), `backend/` (session proxy), raw data files, and `.git`.

**How the AI Assistant works in the bundle:**
- **Cached answers** — 92 instant responses embedded in `docs/cached-answers.js`, loaded on every page. No network needed for these.
- **Lambda fallback** — For questions not in the cache, the widget calls the live Lambda endpoints (hardcoded in `chat-widget.js`). Requires internet access to the Lambda URLs.
- **Voice mode** — WebRTC voice via the live Session Lambda. Requires internet access.

The reviewer gets the full AI-assisted experience without access to the backend implementation.

---

## Known Limitations & Future Improvements

### CDN Dependencies for Interactive Tools

Three of the documentation tools load JavaScript libraries from CDN at runtime:

| Tool | CDN Import | Purpose |
|------|-----------|---------|
| Architecture Diagrams | `mermaid@11` via jsdelivr (~2 MB) | Diagram rendering |
| Parquet Viewer | `hyparquet@1` + `hyparquet-compressors@1` via esm.sh | In-browser Parquet reader |
| SQL Explorer | `hyparquet@1` + `hyparquet-compressors@1` + `squirreling@0` via esm.sh | Browser SQL engine |

**Impact:** These tools require an internet connection. The pipeline itself, all tests, and the comparison report work fully offline — only the interactive documentation tools need network access.

**Future improvement — offline bundling:** For air-gapped or on-prem deployments, these CDN imports could be vendored locally. Mermaid is a single `.min.js` file and trivial to bundle. The `esm.sh` imports (hyparquet, squirreling) resolve transitive dependencies at the CDN edge, so local bundling would require adding a JavaScript build tool (esbuild or rollup), a `package.json`, and a build step. This was intentionally deferred to keep the project as a zero-JS-build Python project — adding JS tooling would increase infrastructure complexity for a feature that is documentation-only and not on the critical path.

### Other Future Improvements

- **Pipeline execution dashboard** — generate an HTML page visualizing pipeline logs: per-step durations, a Gantt-style timeline, throughput metrics (rows/sec), and resource usage. Would make performance regressions and bottlenecks immediately visible.
- **CI/CD pipeline** — GitHub Actions for automated testing on push
- **CloudWatch monitoring** — alarms and dashboards for Lambda pipeline steps
- **End-to-end cloud testing** — deploy and validate pipeline on real AWS infrastructure
- **Report Pal tool calling in voice mode** — proxy `query_database` tool calls from the Realtime API through the chat Lambda for live SQL in voice conversations

---

## Project Structure

```
├── Dockerfile               # Local container build (Python 3.14-slim)
├── entrypoint.sh            # Docker entrypoint: pipeline → tests → docs → web server
├── index.html               # S3 root redirect → docs/index.html
├── pyproject.toml            # pytest configuration
├── README.md                 # This file
├── REVIEWER_README.md        # Guided walkthrough for reviewers (with screenshots)
├── ARCHIVE_README.md         # Orientation page for ZIP bundle recipients
├── FEEDBACK.md               # Assessment feedback (per spec)
├── requirements.txt          # Core Python dependencies
├── requirements-web.txt      # Optional: FastAPI/uvicorn for web upload UI
│
├── src/                      # Core Python pipeline + shared AI chat modules
│   ├── main.py               # Local CLI entry point
│   ├── ingest.py             # CSV → DuckDB loading
│   ├── profile.py            # Column-level data quality profiling
│   ├── validate.py           # Internal consistency checks
│   ├── compare.py            # Old vs New comparison engine
│   ├── report.py             # HTML report + Plotly charts
│   ├── chat_prompt.py        # Shared Report Pal system prompt & tool definitions
│   ├── chat_answers.py       # Pre-cached Q&A pairs for instant responses
│   ├── db_utils.py           # Shared DuckDB utilities
│   ├── templates/
│   │   └── report.html.j2    # Jinja2 HTML report template
│   ├── adapters/
│   │   ├── __init__.py       # StorageAdapter protocol
│   │   ├── local.py          # Local filesystem adapter
│   │   └── aws.py            # S3 storage adapter
│   └── pipeline/
│       ├── __init__.py       # PipelineContext, StepResult
│       ├── runner.py         # Local 6-step orchestrator with gate logic
│       ├── step1_receive.py
│       ├── step2_schema_validate.py
│       ├── step3_ingest.py
│       ├── step4_match.py
│       ├── step5_compare.py
│       └── step6_report.py
│
├── cloud/                    # Cloud Lambda (Python) — pipeline handlers + AI chat
│   ├── Dockerfile            # Lambda container image
│   ├── handlers.py           # Pipeline step handlers + AI chat with query_database tool
│   └── requirements.txt      # Lambda dependencies
│
├── infra/                    # AWS infrastructure-as-code
│   ├── template.yaml         # SAM: S3 + Lambda + Step Functions + API Gateway
│   ├── statemachine.asl.json # Step Functions state machine definition
│   └── samconfig.toml        # SAM deploy configuration
│
├── web/                      # FastAPI web UI (drag-and-drop uploads)
│   └── server.py             # Self-contained server + frontend
│
├── tests/                    # 87 tests (pytest)
│   ├── conftest.py           # Shared fixtures (in-memory DuckDB + sample data)
│   ├── test_compare.py
│   ├── test_pipeline.py      # Pipeline step tests
│   ├── test_profile.py
│   ├── test_real_data.py     # Real CMS data validation (auto-skipped if data not present)
│   ├── test_report.py
│   └── test_validate.py
│
├── scripts/                  # Utility scripts
│   ├── bundle.sh             # Create submission ZIP archive
│   ├── upload_bundle.sh      # Upload bundle to S3 at persistent URL
│   ├── render_md_docs.py     # Convert markdown docs → styled HTML
│   ├── serve.sh              # Start local HTTP server for docs
│   └── teardown_cloud.sh     # AWS resource cleanup
│
├── docs/                     # Documentation hub + AI chat widget
│   ├── index.html            # Landing page (links to all pages)
│   ├── chat-widget.js        # Report Pal: AI chat + WebRTC voice (self-contained)
│   ├── cached-answers.js     # Pre-built Q&A for all pages (generated by pipeline)
│   ├── architecture.html     # Interactive architecture diagrams (Mermaid.js)
│   ├── schema_explorer.html  # Interactive schema explorer (drag, zoom, search)
│   ├── parquet_viewer.html   # In-browser Parquet file viewer (hyparquet)
│   ├── sql_explorer.html     # In-browser SQL queries on Parquet (Squirreling)
│   ├── SOLUTION.md           # Architecture decisions and design rationale
│   ├── REQUIREMENTS_TRACEABILITY.md  # Requirement → implementation mapping
│   ├── DATA_DICTIONARY.md    # Dataset overview, column definitions, codebook ref
│   ├── PIPELINE.md           # Detailed pipeline reference (all checks documented)
│   ├── *.html (6 rendered)   # HTML versions of .md docs (generated by render_md_docs.py)
│   ├── exports → ../reports/exports   # Symlink for web serving
│   └── reports → ../reports           # Symlink for web serving
│
├── specs/                    # Assessment spec + reference materials
│   ├── 02A. Data Engineer Take Home Assessment.md  # Assessment spec
│   ├── DE 1.0 Codebook.pdf                        # CMS DE-SynPUF codebook
│   ├── DE 1.0 Frequently Asked Questions.pdf      # CMS FAQ
│   └── SynPUF_DUG.pdf                             # Data Users Guide
│
├── data/                     # Data directory (large files gitignored)
│   ├── original_downloads/   # Place ZIP archives here (tracked README)
│   ├── old_system/           # Old system CSVs (auto-extracted by Step 1)
│   ├── new_system/           # New system CSVs (when available)
│   └── database/             # DuckDB database (auto-generated by Step 3)
│
├── reports/                  # Pipeline outputs
│   ├── comparison_report.html     # Self-contained HTML report (tracked)
│   └── exports/                   # CSV + Parquet exports (gitignored)
│
└── screenshots/              # Report screenshots for submission (12 PNGs)
```