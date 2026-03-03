# CMS Claims Comparison Pipeline

A data comparison and validation tool that compares outcomes from two healthcare claims processing systems. Given a legacy system's output (CMS DE-SynPUF Medicare data) and a replacement system's output, the pipeline ingests both, validates data quality, matches records, quantifies discrepancies, and generates an interactive report.

Built for the USDS Data Engineering Take-Home Assessment.

---

## Quick Start

### Option A: Docker (recommended)

Docker is the simplest way to run the pipeline on any machine. No Python install required.

```bash
# 1. Build the image
docker build -t cms-pipeline .

# 2. Place your data
#    - Old system CSVs → data/raw/
#    - New system CSVs → data/new/  (when available)

# 3. Run the full pipeline
docker run --rm \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/reports:/app/reports" \
  cms-pipeline

# 4. Run with new system data
docker run --rm \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/reports:/app/reports" \
  cms-pipeline python -m src.main --new-data /app/data/new/

# 5. Skip ingest on re-runs (reuses DuckDB)
docker run --rm \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/reports:/app/reports" \
  cms-pipeline python -m src.main --skip-ingest
```

The report is written to `reports/comparison_report.html`. Open it in any browser.

### Option B: Local Python

```bash
# Requires Python 3.13+ (3.14 recommended)
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Download and place data (see "Data Setup" below)

# Run the pipeline
python -m src.main

# With new system data
python -m src.main --new-data data/new/

# Skip ingest on re-runs
python -m src.main --skip-ingest

# Run tests
pytest tests/ -v
```

### Data Setup

1. Download the **old system** (legacy) files from [CMS DE-SynPUF Sample 1](https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-claims-synthetic-public-use-files/cms-2008-2010-data-entrepreneurs-synthetic-public-use-file-de-synpuf/de10-sample-1):
   - DE1.0 Sample 1 2008 Beneficiary Summary File (ZIP)
   - DE1.0 Sample 1 2009 Beneficiary Summary File (ZIP)
   - DE1.0 Sample 1 2010 Beneficiary Summary File (ZIP)
   - DE1.0 Sample 1 2008-2010 Carrier Claims 1 (ZIP)
   - DE1.0 Sample 1 2008-2010 Carrier Claims 2 (ZIP)

2. Unzip into `data/raw/`:
   ```bash
   mkdir -p data/raw
   for f in data/*.zip; do unzip -o "$f" -d data/raw/; done
   ```

3. *(When available)* Place **new system** CSVs into `data/new/`.

---

## Components

### What You Need

| Component | Purpose | Required? |
|-----------|---------|-----------|
| **Python 3.13+** | Runtime (3.14 recommended) | Yes (or use Docker) |
| **DuckDB** | Analytical database — zero-config, embedded, handles GBs of CSVs natively | Yes (pip install) |
| **Pandas** | DataFrame conversion for chart building | Yes (pip install) |
| **Plotly** | Interactive charts in the HTML report | Yes (pip install) |
| **Jinja2** | HTML report templating | Yes (pip install) |
| **pytest** | Test runner | Dev only |
| **Docker** | Portable containerized execution | Recommended |

All Python dependencies are in `requirements.txt`. There are **no system-level dependencies** beyond Python itself — DuckDB is a pure pip install with no external database server.

### Why Python 3.14?

Python 3.14 (released October 2025) is the latest stable release. All of our dependencies — including DuckDB, which ships compiled C extensions — publish binary wheels for CPython 3.14 across macOS, Linux, and Windows. The Dockerfile pins `python:3.14-slim` to match.

Python 3.13 also works if that's what you have locally. The codebase uses no 3.14-only features.

### Python Libraries

| Library | Version | Why We Use It |
|---------|---------|---------------|
| **duckdb** | ≥1.1.0 | Embedded analytical database. Reads CSVs natively, runs columnar SQL, handles 5M-row tables without a server. The core of our ETL and query engine. |
| **pandas** | ≥2.0.0 | Used only for chart data — `fetchdf()` converts DuckDB results to DataFrames for Plotly. Not used for heavy data processing (DuckDB handles that). |
| **plotly** | ≥5.18.0 | Generates interactive HTML charts (bar, box, scatter). Charts are embedded directly in the report as self-contained HTML — no server needed. |
| **jinja2** | ≥3.1.0 | HTML report templating. The report template is a single Jinja2 string with loops, conditionals, and variable interpolation. |
| **pytest** | ≥8.0.0 | Test runner. Dev dependency only — not needed to run the pipeline. |

### What You Provide

| Input | Description | Format |
|-------|-------------|--------|
| **Old system data** | CMS DE-SynPUF files from cms.gov | 5 CSVs: 3 beneficiary summary (2008-2010) + 2 carrier claims |
| **New system data** | Replacement system output (password-protected zip from assessment) | CSVs with same schema, or a zip file |

The pipeline auto-detects file types by reading CSV headers — it doesn't rely on filenames.

### What You Get

| Output | Location | Description |
|--------|----------|-------------|
| **HTML Report** | `reports/comparison_report.html` | Interactive report with charts, sortable tables, collapsible sections |
| **DuckDB Database** | `data/db/cms_claims.duckdb` | Persistent analytical database — query directly with DuckDB CLI |
| **CSV Exports** | `reports/exports/` | Raw analysis tables (financial reconciliation, match results, discrepancy detail) |

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
│  4. MATCH             Record matching by primary keys   │
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

## CLI Reference

```
python -m src.main [OPTIONS]

Options:
  --new-data PATH    Path to directory or zip containing new system CSVs
  --skip-ingest      Skip ingestion, reuse existing DuckDB database
  --db-path PATH     Custom DuckDB database path (default: data/db/cms_claims.duckdb)
```

---

## Project Structure

```
├── Dockerfile               # Container build (Python 3.14-slim)
├── .dockerignore             # Keep image small
├── .gitignore               # Excludes data/, caches, IDE files
├── README.md                 # This file
├── FEEDBACK.md               # Assessment feedback (per spec)
├── requirements.txt          # Python dependencies
├── screenshots/              # Report screenshots for submission
│
├── specs/
│   ├── solution.md           # Architecture decisions and design rationale
│   └── ...                   # Assessment spec, codebook
│
├── src/
│   ├── __init__.py
│   ├── main.py               # CLI entry point
│   ├── ingest.py             # CSV → DuckDB loading
│   ├── profile.py            # Column-level data quality profiling
│   ├── validate.py           # Internal consistency checks
│   ├── compare.py            # Old vs New comparison engine
│   ├── report.py             # HTML report + Plotly charts
│   └── pipeline/
│       ├── __init__.py       # PipelineContext, StepResult
│       ├── runner.py         # 6-step orchestrator with gate logic
│       ├── step1_receive.py
│       ├── step2_schema_validate.py
│       ├── step3_ingest.py
│       ├── step4_match.py
│       ├── step5_compare.py
│       └── step6_report.py
│
├── tests/                    # 54 tests (pytest)
│   ├── conftest.py           # Shared fixtures (in-memory DuckDB + sample data)
│   ├── test_compare.py
│   ├── test_pipeline.py      # Pipeline step tests
│   ├── test_profile.py
│   ├── test_report.py
│   └── test_validate.py
│
├── data/
│   ├── raw/                  # Old system CSVs (unzipped)
│   ├── new/                  # New system CSVs (when available)
│   └── db/                   # DuckDB database file
│
├── reports/
│   ├── comparison_report.html
│   └── exports/              # CSV exports of analysis tables
│
├── docs/                     # CMS codebook, FAQ, data users guide
└── specs/                    # Assessment specification
```