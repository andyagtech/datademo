# Feedback

## Duration

Approximately 6 hours coding and another two hours for writing, taking screenshots, and other organization.

I spent another 3 hours adding in a chat component from another personal project, and then another half-hour or so loading a version on AWS and automating the screenshot generation. 

I also added a bit more to the data exploration part than was originally asked for - showing the use of an in-browser Parquet viewer and query engine that was made by someone I know.

## Approach

My approach prioritized building a reliable, well-structured pipeline over maximizing the number of checks. The key decisions:

1. **DuckDB** for the analytical workload — SQL is clearer than tools like Pandasfor the complex joins and aggregations needed for matching records. DuckDB is not a trad works on files easily without needed persistent processes.  and can handle the 2.4 GB carrier claims files without memory pressure.

2. **6-step pipeline with gate logic** — rather than a monolithic script, each step is independently testable and can halt early on bad input. This mirrors how production data pipelines should work.

3. **Report designed to communicate, not just display** — executive summary and failed checks upfront, interactive charts for trends, data profiles collapsed as reference material. The report should answer "what's wrong and how bad is it" within 10 seconds of opening.

4. **Docker for portability** — a single `docker build && docker run` command runs the full pipeline on any machine, with data volume-mounted to keep the image small.

5. **Interpretive analysis over raw numbers** — the report doesn't just show discrepancy counts, it explains what they mean: root cause hypotheses, risk assessment, and a clear recommendation (not ready for cutover, two bugs to fix).

## How My Expertise Fits This Assessment

This assessment is fundamentally about **evaluating the migration of a healthcare claims processing system** — exactly the kind of work USDS does when modernizing government systems.

My approach reflects that context:

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

- The assessment is well-scoped — the 4-6 hour estimate is realistic for a decent solution.
- It is a fair evaluation. The open-ended nature (depth of analysis, report medium, tech choices) can let us show off different strengths.
- The CMS DE-SynPUF data is a good choice — it's realistic, publicly available, and large enough to test performance decisions.
- Working off a codebook is .

## Suggestions for Improving the Assessment

- A brief **scoring rubric** (even at a high level — e.g., "we value depth over breadth") could help us figure out the best use of our time.
- As someone who makes data pipelines, I would want to see how candidates handle the other 20 DE-SynPUF samples, and if they make solutions that handle those well. 
