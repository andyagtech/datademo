# Feedback

## Duration

Approximately X hours (update before submission).

## Approach

My approach prioritized building a reliable, well-structured pipeline over maximizing the number of checks. The key decisions:

1. **DuckDB over Pandas** for the analytical workload — SQL is clearer for the complex joins and aggregations needed for financial reconciliation, and DuckDB handles the 2.4 GB carrier claims files without memory pressure.

2. **6-step pipeline with gate logic** — rather than a monolithic script, each step is independently testable and can halt early on bad input. This mirrors how production data pipelines should work.

3. **Report designed to communicate, not just display** — executive summary and failed checks upfront, interactive charts for trends, data profiles collapsed as reference material. The report should answer "what's wrong and how bad is it" within 10 seconds of opening.

4. **Docker for portability** — a single `docker build && docker run` command runs the full pipeline on any machine, with data volume-mounted to keep the image small.

5. **Interpretive analysis over raw numbers** — the report doesn't just show discrepancy counts, it explains what they mean: root cause hypotheses, risk assessment, and a clear recommendation (not ready for cutover, two bugs to fix).

## How My Expertise Fits This Assessment

This assessment is fundamentally about **building trustworthy data infrastructure for a healthcare migration** — exactly the kind of work USDS does when modernizing government systems. My approach reflects that context:

- **Production pipeline thinking:** The 6-step pipeline with gate logic, halting on bad input, and structured error reporting mirrors how I would build a real migration validation tool — not a one-off script, but something a team can maintain and re-run.
- **Domain awareness:** I read the CMS codebook to understand the financial reconciliation rules (LINE_PRCSG_IND_CD filtering, MEDREIMB_CAR derivation). The validation checks are informed by the data's semantics, not just its structure.
- **Communication as a deliverable:** At USDS, the audience for a report like this includes both engineers and non-technical stakeholders. The report is designed for progressive disclosure: KPIs → Key Findings narrative → detailed charts → raw data profiles.
- **Cloud-ready architecture:** The StorageAdapter pattern and AWS SAM infrastructure (Lambda + Step Functions + S3) demonstrate readiness for government cloud environments, even though the assessment only requires local execution.

## Skills Demonstrated

- **Data engineering:** CSV ingestion, schema validation, ETL into an analytical database, data quality profiling, record matching with composite keys
- **SQL:** Complex multi-table joins, UNPIVOT-style queries for 13-line carrier claims, financial reconciliation logic derived from the CMS codebook, window functions for discrepancy analysis
- **Python:** Clean module architecture, dataclasses, type hints, pytest fixtures, Jinja2 templating, FastAPI web server
- **Data analysis:** Identifying anomalies (negative payments, future dates, demographic drift), quantifying discrepancy impact in dollar terms, root cause hypothesis generation, trend analysis
- **Communication:** Interactive HTML report with sidebar navigation, Plotly charts, sortable tables, interpretive Key Findings narrative, risk assessment
- **Infrastructure:** Docker containerization, AWS SAM (Lambda + Step Functions + S3 + API Gateway), StorageAdapter abstraction pattern

## Assessment Feedback

- The assessment is well-scoped — the 4-6 hour estimate is realistic for a baseline solution. The open-ended nature (depth of analysis, report medium, tech choices) lets candidates demonstrate their strengths.
- The CMS DE-SynPUF data is a good choice — it's realistic, publicly available, and large enough to test performance decisions.
- Having the new system data password-protected adds realism but creates a dependency on the link staying active. Consider including the zip directly in the repository or providing a backup download method.
- The codebook is essential for understanding the financial reconciliation logic (e.g., which LINE_PRCSG_IND_CD values to filter on). Candidates who don't read it will miss important validation checks.

## Suggestions for Improving the Assessment

- Consider providing a **sample expected output** (even partial) so candidates can self-validate their comparison logic. Without ground truth, it's hard to know if you've found all the intentional issues.
- A brief **scoring rubric** (even at a high level — e.g., "we value depth over breadth") would help candidates allocate their time effectively.
- The 20 DE-SynPUF samples offer a natural extension: "run your tool against a different sample" would test whether solutions are genuinely reusable vs. hardcoded to Sample 1.
