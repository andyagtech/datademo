# Requirements Traceability

> Maps every requirement from **02A. Data Engineer Take Home Assessment** to how our solution fulfills it.

---

## Purpose Statement Requirements

### REQ-1: Build a data comparison and validation tool

> "Build a small, reliable data comparison and validation tool that compares the outcomes of the two claims processing systems."

**Status: FULFILLED**

| Component | Where | What It Does |
|---|---|---|
| 6-step pipeline | `src/pipeline/step1_receive.py` → `step6_report.py` | Orchestrated by `src/runner.py` with gate logic — halts early on bad input |
| Validation engine | `src/validate.py` | 17 internal consistency checks (identity, temporal, demographic, financial) |
| Comparison engine | `src/compare.py` | 46 cross-system checks (schema, row-level, field-level, aggregate) |
| Record matching | `src/pipeline/step4_match.py` | FULL OUTER JOIN on composite keys to align old/new records |

### REQ-2: Surface issues and inconsistencies

> "The data from the new system intentionally contains issues and inconsistencies, and your goal is to surface them."

**Status: FULFILLED**

Issues surfaced:
- **446 beneficiary records** with at least one field mismatch (out of 343,485 matched)
- **178 BENE_BIRTH_DT mismatches** — largest single source of error
- **10,411 claims** with mismatched `LINE_NCH_PMT_AMT_1` (primary payment)
- **4,777 phantom claims** — exist in new system only, zero lost from old
- **$35,624.71** total financial divergence across 9 reimbursement columns
- All dollar deltas are **positive** — new system overstates, never understates

**Evidence:** `reports/report_data.json` → `chart_data.analysis_findings`, `chart_data.field_mismatches`, `chart_data.claims_payment_mismatches`

### REQ-3: Quantify their impact

> "quantify their impact"

**Status: FULFILLED**

| Metric | Value | Location in Report |
|---|---|---|
| Record-level accuracy | 99.87% | Discrepancy Dashboard KPI + Key Findings |
| Beneficiaries mismatched | 446 / 343,485 | Discrepancy Dashboard KPI |
| Claims payment mismatches | 10,411 on LINE_NCH_PMT_AMT_1 | Discrepancy Dashboard chart |
| Financial divergence | $35,624.71 (0.003% of $1.24B total) | Key Findings narrative + risk assessment |
| Phantom claims | 4,777 new-only, 0 old-only | Key Findings narrative |
| Field-level breakdown | 521 total field diffs across 15+ columns | Field Mismatches by Column chart |

### REQ-4: Identify any trends

> "identify any trends you see"

**Status: FULFILLED**

Trends identified:
- **Year-over-year stability:** Discrepancy rate is 0.12%–0.14% across 2008–2010, suggesting bugs are inherent to migration logic, not time-dependent
- **One-directional financial bias:** Every dollar delta is positive (net = abs = $35,624.71), indicating systematic calculation bias, not random noise
- **Field concentration:** BENE_BIRTH_DT accounts for 34.2% of all field mismatches — consistent across years → systematic date parsing bug
- **Payment column concentration:** LINE_NCH_PMT_AMT_1 has 5x more mismatches than the next column → targeted calculation bug
- **Geographic uniformity:** 50 of 52 state codes have mismatches, no geographic concentration → code-level not data-level issue
- **Service type breakdown:** OP ($14.3K) > IP ($12.4K) > CAR ($8.9K) financial divergence

**Evidence:** Discrepancy Dashboard charts (trend by year, field mismatches, geographic), Key Findings narrative, `SOLUTION.md` Analysis Findings section

### REQ-5: Communicate what they mean for accuracy

> "communicate what they mean for accuracy"

**Status: FULFILLED**

The report includes a **Key Findings** narrative section with:
- Overall accuracy assessment: "99.87% record-level accuracy"
- Root cause hypotheses: "systematic date parsing bug", "systematic calculation bias"
- Risk assessment: "$35,624.71 represents 0.003% of $1.24B total reimbursements — negligible in aggregate"
- Actionable recommendation: "not ready for production cutover" with two specific bugs to fix
- "What This Means for Accuracy" subsection with risk level classification

**Evidence:** HTML report → "Key Findings" + "What This Means for Accuracy" sections (JS-rendered from `analysis_findings` data), `SOLUTION.md` → Analysis Findings section

### REQ-6: Use appropriate language and database

> "Use the language and database you think are most appropriate to the task."

**Status: FULFILLED**

| Choice | Rationale (documented in `SOLUTION.md`) |
|---|---|
| **Python 3.14** | Standard for data engineering; rich ecosystem (pandas, plotly, jinja2) |
| **DuckDB** | Embedded analytical database — zero-config, handles 2.4GB CSVs natively, columnar engine optimized for aggregations on wide tables |

Alternatives considered and rejected: SQLite (row-oriented), PostgreSQL (requires server), Spark (overkill), Pandas-only (fragile at scale). All documented in `specs/SOLUTION.md`.

### REQ-7: Provide a way to review results

> "There should be a way for users to review the results, it could be an excel, charts, basic web view, tableau or whatever medium you find best communicates your findings."

**Status: FULFILLED — multiple review interfaces provided**

| Interface | Location | Description |
|---|---|---|
| **Interactive HTML report** | `reports/comparison_report.html` | Self-contained single file with sidebar nav, Plotly charts, sortable tables, collapsible sections |
| **JSON data artifact** | `reports/report_data.json` | Machine-readable canonical data — can be consumed by any tool |
| **CSV exports** | `reports/exports/*.csv` | Raw diff tables (discrepancy_detail, financial_recon, match results) — openable in Excel |
| **Web UI** | `web/server.py` | FastAPI drag-and-drop upload interface for running the pipeline from a browser |
| **React diff viewer** | `viewer/` | Interactive record-level diff viewer (demo data) |
| **DuckDB database** | `data/db/cms_claims.duckdb` | Query directly with DuckDB CLI for ad-hoc analysis |

### REQ-8: Be prepared to explain code and design decisions

> "Be prepared to explain your code and design decisions."

**Status: FULFILLED**

| Document | Content |
|---|---|
| `specs/SOLUTION.md` | Architecture decisions, design rationale for DuckDB/pipeline/Docker/report, analysis findings, deployment strategy, testing approach |
| `docs/PIPELINE.md` | 492-line reference documenting all 6 pipeline steps, data model, 57 validation/comparison checks, output artifacts |
| `docs/DATA_DICTIONARY.md` | Dataset overview, column definitions for all tables, codebook reference |
| `docs/architecture.html` | Interactive Mermaid.js architecture diagrams |
| Inline code | Docstrings, type hints, clear module separation |

### REQ-9: Depth of analysis, analysis strategy, supporting documentation

> "your depth of analysis, analysis strategy, and supporting documentation providing evidence of your work will be key factors"

**Status: FULFILLED**

| Dimension | Evidence |
|---|---|
| **Depth** | 6 named findings with root cause hypotheses, financial breakdown by service type, geographic distribution analysis, trend stability assessment, risk quantification ($35K on $1.24B) |
| **Strategy** | Old system as ground truth → FULL OUTER JOIN matching → field-level diff flags → aggregate analysis → interpretive narrative. Documented in `SOLUTION.md` and `PIPELINE.md` |
| **Documentation** | 5 docs: README.md, SOLUTION.md, PIPELINE.md, DATA_DICTIONARY.md, FEEDBACK.md. Architecture diagrams. 54 automated tests. |

---

## Comparison Tool Objectives

### REQ-10: Ingest and clean the data

> "Ingest and clean the data."

**Status: FULFILLED**

| Step | Source | What It Does |
|---|---|---|
| Step 1: Receive | `step1_receive.py` | File discovery, zip extraction, SHA-256 checksums, file inventory |
| Step 2: Schema Validate | `step2_schema_validate.py` | Header validation, file classification (beneficiary vs carrier), schema compatibility checks |
| Step 3: Ingest & Profile | `step3_ingest.py` + `src/ingest.py` | CSV → DuckDB loading with type inference, null detection, summary_year derivation from filename, column profiling (nulls, distinct, min/max/mean) |

Cleaning: DuckDB handles type coercion during ingest. The pipeline validates headers before loading (fail-fast on malformed input). Column profiling identifies data quality issues (high-null columns, unexpected values).

### REQ-11: Build a simple ETL pipeline into a database

> "Build a simple ETL pipeline into a database or lightweight datastore of your choice."

**Status: FULFILLED**

- **E (Extract):** CSV files read from local filesystem or S3 via `StorageAdapter` pattern
- **T (Transform):** DuckDB SQL — summary_year derivation, FULL OUTER JOIN matching, field-level diff computation, financial reconciliation aggregation
- **L (Load):** DuckDB embedded database at `data/db/cms_claims.duckdb`

Tables created: `beneficiary_summary`, `carrier_claims`, `new_beneficiary_summary`, `new_carrier_claims`, `_match_beneficiary`, `_match_claims`, `_discrepancy_detail`, `_financial_recon`

### REQ-12: Identify and quantify discrepancies

> "Identify and quantify discrepancies, keep an eye out for identifiable trends."

**Status: FULFILLED**

See REQ-2 (surface), REQ-3 (quantify), and REQ-4 (trends) above.

### REQ-13: Provide specific metrics

> "Provide metrics that helps explain where and why the systems diverge. Examples: Total number of Beneficiaries whose data does not match, Total number of Claims whose payments don't match, Other discrepancy trends."

**Status: FULFILLED**

| Requested Metric | Our Value | Where |
|---|---|---|
| **Beneficiaries whose data does not match** | 446 out of 343,485 (0.13%) | Discrepancy Dashboard KPI card + Key Findings |
| **Claims whose payments don't match** | 10,411 on LINE_NCH_PMT_AMT_1; 657 on LINE_ALOWD_CHRG_AMT_1; 651 on LINE_COINSRNC_AMT_1; 635 on LINE_BENE_PTB_DDCTBL_AMT_1 | Discrepancy Dashboard "Claims Payment Mismatches" chart |
| **Other discrepancy trends** | Year-over-year stability, one-directional financial bias, field concentration (BENE_BIRTH_DT = 34.2%), geographic uniformity, phantom claims (4,777 new-only) | Key Findings narrative, Discrepancy Dashboard charts, SOLUTION.md Analysis Findings |

### REQ-14: Generate a report

> "Generate a report that communicates your findings."

**Status: FULFILLED**

The HTML report (`reports/comparison_report.html`) includes:
- **Sidebar navigation** with active section highlighting
- **Data Context** — what's being compared (file inventories, match results)
- **Executive Summary** — 4 KPI cards, failed checks highlighted
- **Discrepancy Dashboard** — 4 KPI cards, 4 interactive charts, Key Findings narrative with accuracy assessment
- **Validation Results** — 17-check table + bar chart
- **Year-over-Year Trends** — beneficiary count, claims count charts
- **Financial Analysis** — reimbursement trends, payment distribution, chronic condition prevalence
- **System Comparison** — 46-check collapsible table
- **Data Profiles** — collapsible column-level quality profiles for all tables

---

## Submission Requirements

### REQ-15: Source code

> "Source code."

**Status: FULFILLED**

All source code in `src/`, `web/`, `cloud/`, `infra/`, `viewer/`, `tests/`. Git history preserved.

### REQ-16: Comparison report or link to UI

> "Your comparison report or a link to your UI if applicable."

**Status: FULFILLED**

- `reports/comparison_report.html` — self-contained HTML report (open directly in browser)
- `reports/report_data.json` — machine-readable data
- `reports/exports/*.csv` — raw analysis tables
- Web UI available via `python -m uvicorn web.server:app`

### REQ-17: Screenshots

> "Screenshots of your report, output or UI."

**Status: ⚠️ GAP — screenshots directory is empty (placeholder README only)**

The `screenshots/` directory contains only a `README.md` with instructions. **Actual screenshots need to be captured and added before submission.**

Required screenshots:
1. Executive Summary (top of report)
2. Discrepancy Dashboard with Key Findings
3. Year-over-Year Trends charts
4. Financial Analysis charts
5. System Comparison (collapsible)
6. Data Profiles (expanded)
7. Web UI upload interface (optional but impressive)

### REQ-18: README.md

> "A README.md that describes your project and how to run it."

**Status: FULFILLED**

`README.md` (395 lines) includes:
- Project description
- Quick Start (Docker + local)
- Web UI instructions
- Data setup instructions with download links
- Architecture overview (components, dependencies)
- Input/output descriptions
- Validation checks reference
- CLI usage
- AWS cloud deployment instructions
- Project structure tree

### REQ-19: FEEDBACK.md

> "A FEEDBACK.md that includes: Feedback on the assignment, Duration, How expertise/skillsets fit, Anything to help better evaluate candidates."

**Status: ⚠️ PARTIAL — duration placeholder not filled in**

| Section | Status |
|---|---|
| **Duration** | ❌ Still says "Approximately X hours" — needs updating |
| **Approach** | ✅ 4 numbered points explaining key decisions |
| **Skills Demonstrated** | ✅ 5 categories (data engineering, SQL, Python, analysis, communication) |
| **Assessment Feedback** | ✅ 4 bullet points with constructive feedback |

**Missing:** The "how your expertise / skillsets fit this assessment" is partially addressed in "Skills Demonstrated" but could be more explicit about USDS-relevant experience. Also missing: "Anything you think might help the assessment better evaluate candidates" as a distinct section.

---

## Summary of Gaps

| # | Gap | Severity | Action Required |
|---|---|---|---|
| 1 | **Screenshots missing** | HIGH | Capture screenshots of report sections and web UI, add to `screenshots/` |
| 2 | **FEEDBACK.md duration** | MEDIUM | Replace "Approximately X hours" with actual time |
| 3 | **FEEDBACK.md completeness** | LOW | Could add explicit "expertise fit" and "evaluation suggestions" subsections |
