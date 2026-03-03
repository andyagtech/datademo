# Feedback

## Duration

Approximately X hours (update before submission).

## Approach

My approach prioritized building a reliable, well-structured pipeline over maximizing the number of checks. The key decisions:

1. **DuckDB over Pandas** for the analytical workload — SQL is clearer for the complex joins and aggregations needed for financial reconciliation, and DuckDB handles the 2.4 GB carrier claims files without memory pressure.

2. **6-step pipeline with gate logic** — rather than a monolithic script, each step is independently testable and can halt early on bad input. This mirrors how production data pipelines should work.

3. **Report designed to communicate, not just display** — executive summary and failed checks upfront, interactive charts for trends, data profiles collapsed as reference material. The report should answer "what's wrong and how bad is it" within 10 seconds of opening.

4. **Docker for portability** — a single `docker build && docker run` command runs the full pipeline on any machine, with data volume-mounted to keep the image small.

## Skills Demonstrated

- **Data engineering:** CSV ingestion, schema validation, ETL into an analytical database, data quality profiling
- **SQL:** Complex multi-table joins, UNPIVOT-style queries for 13-line carrier claims, financial reconciliation logic derived from the CMS codebook
- **Python:** Clean module architecture, dataclasses, type hints, pytest fixtures, Jinja2 templating
- **Data analysis:** Identifying anomalies (negative payments, future dates, demographic drift), quantifying discrepancy impact in dollar terms
- **Communication:** Interactive HTML report with sortable tables, collapsible sections, Plotly charts, and a clear information hierarchy

## Assessment Feedback

- The assessment is well-scoped — the 4-6 hour estimate is realistic for a baseline solution. The open-ended nature (depth of analysis, report medium, tech choices) lets candidates demonstrate their strengths.
- The CMS DE-SynPUF data is a good choice — it's realistic, publicly available, and large enough to test performance decisions.
- Having the new system data password-protected adds realism but creates a dependency on the link staying active. Consider including the zip directly in the repository or providing a backup download method.
- The codebook is essential for understanding the financial reconciliation logic (e.g., which LINE_PRCSG_IND_CD values to filter on). Candidates who don't read it will miss important validation checks.
