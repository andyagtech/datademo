# Archive Contents

This ZIP archive contains the complete CMS Claims Comparison Pipeline — source code, data, reports, documentation, and screenshots. Everything needed to run, review, and evaluate the project.

---

## Where to Start

| If you want to... | Go here |
|---|---|
| **See the report immediately (no setup)** | [Hosted Comparison Report](http://andy-barr-cmsdata-assessment.s3-website-us-west-2.amazonaws.com/reports/comparison_report.html) |
| **Read the guided walkthrough** | [Hosted Reviewer Walkthrough](http://andy-barr-cmsdata-assessment.s3-website-us-west-2.amazonaws.com/docs/reviewer_readme.html) |
| **Browse all documentation online** | [Hosted Documentation Hub](http://andy-barr-cmsdata-assessment.s3-website-us-west-2.amazonaws.com/docs/index.html) |
| **Run it locally** | See `README.md` → Quick Start |
| **Understand the approach** | `REVIEWER_README.md` or `FEEDBACK.md` |

---

## Archive Structure

```
cmsdata-assessment/
│
├── README.md                    # Project overview, setup, architecture
├── REVIEWER_README.md           # Guided walkthrough with screenshots
├── FEEDBACK.md                  # Assessment feedback (per spec)
├── ARCHIVE_README.md            # This file
│
├── reports/
│   ├── comparison_report.html   # ★ Primary deliverable — interactive HTML report
│   └── report_data.json         # Raw report data (JSON)
│
├── screenshots/                 # 12 screenshots referenced by REVIEWER_README.md
│   ├── screenshot_1.png         # Pipeline run output
│   ├── screenshot_2.png         # Test suite (87 passed)
│   ├── screenshot_3.png         # Report: Executive Summary
│   ├── screenshot_4.png         # Report: Key Findings
│   ├── screenshot_5.png         # Report: Validation Results
│   ├── screenshot_6.png         # Report: Financial Reconciliation
│   ├── screenshot_7.png         # Report: System Comparison
│   ├── screenshot_8.png         # Report: Year-over-Year Trends
│   ├── screenshot_9.png         # Documentation Hub landing page
│   ├── screenshot_10.png        # Schema Explorer
│   ├── screenshot_11.png        # SQL Explorer
│   └── screenshot_12.png        # Parquet Viewer
│
├── docs/                        # Documentation site (open index.html)
│   ├── index.html               # Landing page with links to everything
│   ├── reviewer_readme.html     # Rendered walkthrough with embedded screenshots
│   ├── architecture.html        # Interactive architecture diagrams (Mermaid.js)
│   ├── schema_explorer.html     # Drag-and-drop ERD viewer
│   ├── sql_explorer.html        # In-browser SQL on Parquet files
│   ├── parquet_viewer.html      # In-browser Parquet file viewer
│   ├── solution.html            # Design decisions
│   ├── pipeline.html            # Pipeline reference
│   ├── data_dictionary.html     # Data dictionary
│   ├── requirements_traceability.html  # Spec → implementation mapping
│   └── feedback.html            # Assessment feedback
│
├── src/                         # Source code
│   ├── main.py                  # Entry point
│   ├── pipeline/                # 6-step pipeline with gate logic
│   ├── ingest.py                # CSV ingestion into DuckDB
│   ├── validate.py              # Data quality & financial reconciliation
│   ├── compare.py               # Old-vs-new comparison engine
│   ├── report.py                # HTML report generation (Plotly + Jinja2)
│   ├── profile.py               # Table profiling
│   └── templates/report.html.j2 # Report template
│
├── tests/                       # 87 tests (54 synthetic + 33 real-data)
│
├── data/
│   ├── old_system/              # CMS DE-SynPUF Sample 1 CSVs (5 files)
│   ├── new_system/              # New system CSVs for comparison (5 files)
│   ├── original_downloads/      # Original ZIP downloads from CMS
│   └── database/                # DuckDB database (auto-generated)
│
├── cloud/                       # AWS Lambda deployment code
├── infra/                       # SAM/CloudFormation templates
├── scripts/                     # Utility scripts (bundle, serve, render)
├── specs/                       # Original assessment specification
│
├── Dockerfile                   # Docker build (one command to run everything)
├── entrypoint.sh                # Docker entrypoint
├── requirements.txt             # Python dependencies
└── pyproject.toml               # Project metadata
```

---

## Running the Pipeline

```bash
# Docker (recommended — no Python install required)
docker build -t cms-pipeline .
docker run --rm -p 8888:8888 \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/reports:/app/reports" \
  cms-pipeline

# Or locally
pip install -r requirements.txt
python -m src.main --new-data data/new_system/
./scripts/serve.sh    # http://localhost:8888
```

---

## Running Tests

```bash
pytest tests/ -v    # 87 tests, ~3 seconds
```
