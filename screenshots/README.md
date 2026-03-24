# Screenshots

Screenshots referenced by [`REVIEWER_README.md`](../REVIEWER_README.md). Each image corresponds to a section of the reviewer walkthrough.

## How to capture

1. Run the pipeline: `python -m src.main --new-data data/new_system/`
2. Run the tests: `pytest tests/ -v`
3. Open `reports/comparison_report.html` in a browser
4. Open `docs/index.html` in a browser
5. Take screenshots as described below and save them here

## Screenshot list

| File | Section | What to capture |
|------|---------|-----------------|
| `screenshot_1.png` | Pipeline Run | Terminal showing all 6 steps completing with status messages |
| `screenshot_2.png` | Test Suite | Terminal showing `95 passed` output from `pytest tests/ -v` |
| `screenshot_3.png` | Executive Summary | Top of the report — KPIs, pass/fail indicators, matched counts |
| `screenshot_4.png` | Key Findings | Narrative section — root cause hypotheses, risk assessment, recommendation |
| `screenshot_5.png` | Validation Results | Bar chart of issues per check (identity, temporal, demographic, financial) |
| `screenshot_6.png` | Financial Reconciliation | MEDREIMB_CAR / BENRES_CAR / PPPYMT_CAR mismatch details with dollar amounts |
| `screenshot_7.png` | System Comparison | Old-vs-new dashboard — schema diffs, row-level, field-level, aggregates |
| `screenshot_8.png` | Year-over-Year Trends | Interactive Plotly charts showing 2008–2010 trends |
| `screenshot_9.png` | Documentation Hub | `docs/index.html` landing page with card grid |
| `screenshot_10.png` | Schema Explorer | `docs/schema_explorer.html` — ERD viewer with table cards, column details, zoom/pan |
| `screenshot_11.png` | SQL Explorer | `docs/sql_explorer.html` — query editor with sample SQL results against Parquet files |
| `screenshot_12.png` | Parquet Viewer | `docs/parquet_viewer.html` — drag-and-drop file viewer showing schema and data preview |
