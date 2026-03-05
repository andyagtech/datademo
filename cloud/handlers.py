"""
AWS Lambda handlers for the CMS Claims Comparison Pipeline.

Each handler wraps a pipeline step, providing the Lambda entry point.
Step Functions passes state between handlers via the event dict.

Environment variables (set by SAM template):
  - BUCKET_NAME: S3 bucket for data and reports
  - DATA_PREFIX: S3 prefix for input data (e.g., "uploads/{run_id}")
  - DB_PATH: Path for DuckDB database in /tmp (ephemeral)

Lambda configuration:
  - Runtime: Python 3.14 (container image)
  - Memory: 10240 MB for ingest/compare steps, 1024 MB for lighter steps
  - Timeout: 900s (15 min) for ingest/compare, 300s for others
  - Ephemeral storage: 10240 MB (/tmp)
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import boto3
import duckdb

from src.adapters.aws import S3Storage
from src.pipeline import PipelineContext, StepResult
from src.pipeline.step1_receive import run as step1_run
from src.pipeline.step2_schema_validate import run as step2_run
from src.pipeline.step3_ingest import run as step3_run
from src.pipeline.step4_match import run as step4_run
from src.pipeline.step5_compare import run as step5_run
from src.pipeline.step6_report import run as step6_run

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_storage() -> S3Storage:
    """Build S3Storage adapter from environment variables."""
    bucket = os.environ["BUCKET_NAME"]
    prefix = os.environ.get("DATA_PREFIX", "")
    return S3Storage(bucket=bucket, prefix=prefix)


def _build_context(event: dict[str, Any]) -> PipelineContext:
    """
    Build a PipelineContext from a Lambda event.

    The event carries:
      - run_id: unique pipeline execution ID
      - old_data_prefix: S3 prefix for old system CSVs
      - new_data_prefix: S3 prefix for new system CSVs (optional)
      - results: accumulated results from prior steps
      - halted / halt_reason: gate state
    """
    storage = _get_storage()
    run_id = event.get("run_id", "default")

    # DuckDB database in Lambda ephemeral storage
    db_path = Path(tempfile.gettempdir()) / f"cms_{run_id}.duckdb"

    # Old data dir — for local-compatible path resolution in steps
    # In cloud mode, steps should use ctx.storage instead
    old_prefix = event.get("old_data_prefix", "raw")
    new_prefix = event.get("new_data_prefix")

    ctx = PipelineContext(
        old_data_dir=Path(f"/tmp/{old_prefix}"),  # placeholder for cloud
        new_data_dir=Path(f"/tmp/{new_prefix}") if new_prefix else None,
        db_path=db_path,
        storage=storage,
        skip_ingest=event.get("skip_ingest", False),
        mode="cloud",
        results=event.get("results", {}),
        halted=event.get("halted", False),
        halt_reason=event.get("halt_reason", ""),
    )

    return ctx


def _serialize_result(result: StepResult, ctx: PipelineContext) -> dict[str, Any]:
    """
    Serialize step result + context state for Step Functions.

    This becomes the output of the Lambda and the input to the next step.
    """
    return {
        "run_id": ctx.results.get("run_id", "default"),
        "old_data_prefix": str(ctx.old_data_dir).replace("/tmp/", ""),
        "new_data_prefix": str(ctx.new_data_dir).replace("/tmp/", "") if ctx.new_data_dir else None,
        "results": ctx.results,
        "halted": ctx.halted,
        "halt_reason": ctx.halt_reason,
        "last_step": {
            "name": result.step_name,
            "success": result.success,
            "message": result.message,
            "errors": result.errors,
            "warnings": result.warnings,
        },
    }


def _close_db(ctx: PipelineContext) -> None:
    """Close DuckDB connection if open."""
    if ctx.con:
        try:
            ctx.con.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# API Gateway trigger — starts the Step Functions state machine
# ---------------------------------------------------------------------------

def handle_start_pipeline(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler triggered by API Gateway POST /pipeline/start.

    Accepts a JSON body with:
      - old_data_prefix: S3 prefix where old system CSVs are uploaded
      - new_data_prefix: S3 prefix where new system CSVs are (optional)

    Starts the Step Functions state machine and returns the execution ARN.
    """
    import uuid

    sfn = boto3.client("stepfunctions")
    state_machine_arn = os.environ["STATE_MACHINE_ARN"]

    # Parse body from API Gateway
    body = event.get("body", "{}")
    if isinstance(body, str):
        body = json.loads(body)

    run_id = body.get("run_id", str(uuid.uuid4())[:8])
    old_prefix = body.get("old_data_prefix", "raw")
    new_prefix = body.get("new_data_prefix")

    sfn_input = {
        "run_id": run_id,
        "old_data_prefix": old_prefix,
        "new_data_prefix": new_prefix,
        "results": {"run_id": run_id},
        "halted": False,
        "halt_reason": "",
    }

    execution = sfn.start_execution(
        stateMachineArn=state_machine_arn,
        name=f"run-{run_id}",
        input=json.dumps(sfn_input),
    )

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "run_id": run_id,
            "execution_arn": execution["executionArn"],
            "status": "RUNNING",
            "message": f"Pipeline started. Upload data to s3://{os.environ['BUCKET_NAME']}/{old_prefix}/",
        }),
    }


# ---------------------------------------------------------------------------
# Step handlers — one per Lambda function
# ---------------------------------------------------------------------------

def handle_receive(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for Step 1: Receive & Verify."""
    logger.info(f"Step 1 — Receive: {json.dumps(event, default=str)[:500]}")
    ctx = _build_context(event)
    result = step1_run(ctx)
    return _serialize_result(result, ctx)


def handle_schema_validate(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for Step 2: Schema Validate."""
    logger.info(f"Step 2 — Schema Validate: {json.dumps(event, default=str)[:500]}")
    ctx = _build_context(event)
    result = step2_run(ctx)
    return _serialize_result(result, ctx)


def handle_ingest(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for Step 3: Ingest & Profile."""
    logger.info(f"Step 3 — Ingest: {json.dumps(event, default=str)[:500]}")
    ctx = _build_context(event)

    # Open DuckDB in /tmp for this step
    ctx.con = duckdb.connect(str(ctx.db_path))

    # Enable S3 access via httpfs
    ctx.con.execute("INSTALL httpfs; LOAD httpfs;")
    ctx.con.execute("SET s3_region = 'us-east-1';")

    try:
        result = step3_run(ctx)

        # Snapshot the DuckDB file to S3 for downstream steps
        if ctx.db_path and ctx.db_path.exists():
            storage = _get_storage()
            run_id = event.get("run_id", "default")
            db_s3_key = f"runs/{run_id}/cms_claims.duckdb"
            storage.write_bytes(db_s3_key, ctx.db_path.read_bytes())
            ctx.results["db_s3_key"] = db_s3_key
            logger.info(f"DuckDB snapshot uploaded to {db_s3_key}")
    finally:
        _close_db(ctx)

    return _serialize_result(result, ctx)


def handle_match(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for Step 4: Match & Validate."""
    logger.info(f"Step 4 — Match: {json.dumps(event, default=str)[:500]}")
    ctx = _build_context(event)

    # Restore DuckDB from S3 snapshot
    _restore_db(ctx, event)

    try:
        result = step4_run(ctx)
        _snapshot_db(ctx, event)
    finally:
        _close_db(ctx)

    return _serialize_result(result, ctx)


def handle_compare(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for Step 5: Compare & Analyze."""
    logger.info(f"Step 5 — Compare: {json.dumps(event, default=str)[:500]}")
    ctx = _build_context(event)

    _restore_db(ctx, event)

    try:
        result = step5_run(ctx)
        _snapshot_db(ctx, event)
    finally:
        _close_db(ctx)

    return _serialize_result(result, ctx)


def handle_report(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for Step 6: Report Generation."""
    logger.info(f"Step 6 — Report: {json.dumps(event, default=str)[:500]}")
    ctx = _build_context(event)

    _restore_db(ctx, event)

    try:
        result = step6_run(ctx)

        # Upload the report HTML to S3
        report_path = ctx.results.get("report", {}).get("report_path")
        if report_path and Path(report_path).exists():
            storage = _get_storage()
            run_id = event.get("run_id", "default")
            report_key = f"runs/{run_id}/report.html"
            storage.write_bytes(report_key, Path(report_path).read_bytes())
            presigned = storage.generate_presigned_url(report_key, expires_in=86400)
            ctx.results["report"]["report_url"] = presigned
            logger.info(f"Report uploaded: {report_key}")
    finally:
        _close_db(ctx)

    return _serialize_result(result, ctx)


# ---------------------------------------------------------------------------
# DB snapshot helpers (pass DuckDB between Lambda invocations via S3)
# ---------------------------------------------------------------------------

def _restore_db(ctx: PipelineContext, event: dict[str, Any]) -> None:
    """Download DuckDB snapshot from S3 to /tmp and open a connection."""
    db_s3_key = event.get("results", {}).get("db_s3_key")
    if not db_s3_key:
        logger.warning("No DuckDB snapshot key found in event — opening fresh DB")
        ctx.con = duckdb.connect(str(ctx.db_path))
        return

    storage = _get_storage()
    db_bytes = storage.read_bytes(db_s3_key)
    ctx.db_path.write_bytes(db_bytes)
    logger.info(f"Restored DuckDB from {db_s3_key} ({len(db_bytes) / 1024 / 1024:.1f} MB)")

    ctx.con = duckdb.connect(str(ctx.db_path))


def _snapshot_db(ctx: PipelineContext, event: dict[str, Any]) -> None:
    """Upload current DuckDB file to S3 for the next step."""
    if ctx.con:
        ctx.con.close()
        ctx.con = None

    if ctx.db_path and ctx.db_path.exists():
        storage = _get_storage()
        run_id = event.get("run_id", "default")
        db_s3_key = f"runs/{run_id}/cms_claims.duckdb"
        storage.write_bytes(db_s3_key, ctx.db_path.read_bytes())
        ctx.results["db_s3_key"] = db_s3_key
        logger.info(f"DuckDB snapshot uploaded: {db_s3_key}")

    # Re-open for any further use in this invocation
    ctx.con = duckdb.connect(str(ctx.db_path))


# ---------------------------------------------------------------------------
# AI Chat handler — Lambda behind API Gateway
# ---------------------------------------------------------------------------

# Module-level caches (persist across warm Lambda invocations)
_cached_api_key: str | None = None
_cached_db_con: Any | None = None  # live duckdb.Connection with views over Parquet

_MAX_ROWS = 50
_MAX_TOOL_ROUNDS = 5


def _get_openai_api_key() -> str:
    """Retrieve OpenAI API key from SSM Parameter Store (cached)."""
    global _cached_api_key
    if _cached_api_key:
        return _cached_api_key

    ssm = boto3.client("ssm")
    param_name = os.environ.get("OPENAI_API_KEY_SSM", "/cms-pipeline/openai-api-key")
    resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
    _cached_api_key = resp["Parameter"]["Value"]
    return _cached_api_key


_PARQUET_TABLES = [
    "beneficiary_summary",
    "carrier_claims",
    "new_beneficiary_summary",
    "new_carrier_claims",
    "_discrepancy_detail",
    "_financial_recon",
    "_match_beneficiary",
    "_match_claims",
]


def _ensure_db_ready(event: dict[str, Any]):
    """Download Parquet files from S3 and return an in-memory DuckDB connection with views.

    Much faster than downloading the 1.6 GB DuckDB file (~488 MB of Parquet).
    On warm invocations the connection and Parquet files are already cached.
    Returns a live duckdb.Connection — do NOT close it (it's reused across invocations).
    """
    global _cached_db_con

    # Warm invocation — connection already cached
    if _cached_db_con is not None:
        logger.info("Using cached DuckDB connection + Parquet files")
        return _cached_db_con

    parquet_dir = Path(tempfile.gettempdir()) / "parquet"
    parquet_dir.mkdir(parents=True, exist_ok=True)

    # S3 prefix for parquet files
    parquet_prefix = os.environ.get("PARQUET_S3_PREFIX", "runs/latest/parquet")
    storage = _get_storage()
    total_bytes = 0

    for table_name in _PARQUET_TABLES:
        s3_key = f"{parquet_prefix}/{table_name}.parquet"
        local_file = parquet_dir / f"{table_name}.parquet"
        if not local_file.exists():
            data = storage.read_bytes(s3_key)
            local_file.write_bytes(data)
            total_bytes += len(data)
            logger.info(f"Downloaded {s3_key} ({len(data) / 1024 / 1024:.1f} MB)")

    logger.info(f"Total Parquet download: {total_bytes / 1024 / 1024:.1f} MB")

    # Build in-memory DuckDB with lazy views (stays open for warm reuse)
    # Try to EXCLUDE duckdb_schema metadata column (causes binder errors with aliases)
    con = duckdb.connect(":memory:")
    for table_name in _PARQUET_TABLES:
        pq_path = str(parquet_dir / f"{table_name}.parquet")
        try:
            con.execute(f'CREATE VIEW "{table_name}" AS SELECT * EXCLUDE (duckdb_schema) FROM read_parquet(\'{pq_path}\')')
        except Exception:
            con.execute(f'CREATE VIEW "{table_name}" AS SELECT * FROM read_parquet(\'{pq_path}\')')
    logger.info("Built in-memory DuckDB with views over Parquet files")

    _cached_db_con = con
    return con


def _chat_execute_query(con, sql: str) -> dict:
    """Execute a read-only SQL query against the cached DuckDB connection."""
    sql_stripped = sql.strip().rstrip(";").strip()
    first_word = sql_stripped.split()[0].upper() if sql_stripped else ""
    if first_word not in ("SELECT", "WITH", "EXPLAIN", "DESCRIBE", "SHOW", "PRAGMA"):
        return {"error": f"Only SELECT/WITH/EXPLAIN/DESCRIBE queries are allowed. Got: {first_word}"}

    try:
        result = con.execute(sql_stripped)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchmany(_MAX_ROWS + 1)
        truncated = len(rows) > _MAX_ROWS
        if truncated:
            rows = rows[:_MAX_ROWS]
        clean_rows = []
        for row in rows:
            clean_row = []
            for val in row:
                if val is None:
                    clean_row.append(None)
                elif isinstance(val, (int, float, bool, str)):
                    clean_row.append(val)
                else:
                    clean_row.append(str(val))
            clean_rows.append(clean_row)
        return {
            "columns": columns,
            "rows": clean_rows,
            "row_count": len(clean_rows),
            "truncated": truncated,
        }
    except Exception as e:
        return {"error": f"Query failed: {str(e)}"}


def _build_chat_findings(con) -> str:
    """Build findings context by querying the cached DuckDB connection."""
    lines = []
    try:
        # Basic counts
        bene_count = con.execute("SELECT COUNT(*) FROM beneficiary_summary").fetchone()[0]
        claim_count = con.execute("SELECT COUNT(*) FROM carrier_claims").fetchone()[0]
        lines.append(f"- Total beneficiaries (old): {bene_count:,}")
        lines.append(f"- Total carrier claims (old): {claim_count:,}")

        # Check for new system tables
        try:
            new_bene = con.execute("SELECT COUNT(*) FROM new_beneficiary_summary").fetchone()[0]
            new_claims = con.execute("SELECT COUNT(*) FROM new_carrier_claims").fetchone()[0]
            lines.append(f"- Total beneficiaries (new): {new_bene:,}")
            lines.append(f"- Total carrier claims (new): {new_claims:,}")
        except Exception:
            lines.append("- New system tables not available")

        # Discrepancy summary
        try:
            disc = con.execute("SELECT COUNT(*), SUM(total_diffs) FROM _discrepancy_detail WHERE total_diffs > 0").fetchone()
            lines.append(f"- Beneficiaries with discrepancies: {disc[0]:,} ({disc[1]:,} total diffs)")
        except Exception:
            pass

        # Match status
        try:
            match_stats = con.execute("""
                SELECT match_status, COUNT(*) as cnt
                FROM _match_beneficiary
                GROUP BY match_status
            """).fetchall()
            for status, cnt in match_stats:
                lines.append(f"- Beneficiary match '{status}': {cnt:,}")
        except Exception:
            pass

    except Exception as e:
        lines.append(f"- Could not query database for findings: {e}")

    return "\n".join(lines) if lines else "Database available but no summary could be built."


# System prompt (same as web/server.py but loaded here for Lambda)
_LAMBDA_SYSTEM_PROMPT = """You are a data analysis assistant embedded in the CMS Claims Comparison Report.
You help reviewers understand the findings from comparing an old Medicare claims processing
system (CMS DE-SynPUF) against a new replacement system.

You have deep knowledge of:
- Medicare beneficiary summary data (demographics, chronic conditions, coverage months, financials)
- Carrier claims data (diagnosis codes, procedure codes, provider NPIs, payment line items)
- Data quality validation checks (key integrity, temporal consistency, demographic consistency, financial reconciliation)

## Key Findings
{findings_context}

## Database Access
You have direct access to the DuckDB database via the `query_database` tool.
Use SELECT queries only — the database is read-only. Always add LIMIT (max 50).

### Database Schema
**beneficiary_summary** / **new_beneficiary_summary** (33 cols each):
  Key: DESYNPUF_ID + summary_year.
  Demographics: BENE_BIRTH_DT, BENE_DEATH_DT, BENE_SEX_IDENT_CD, BENE_RACE_CD, SP_STATE_CODE, BENE_COUNTY_CD.
  Coverage: BENE_HI_CVRAGE_TOT_MONS, BENE_SMI_CVRAGE_TOT_MONS, BENE_HMO_CVRAGE_TOT_MONS, PLAN_CVRG_MOS_NUM.
  Chronic conditions (1=yes): SP_ALZHDMTA, SP_CHF, SP_CHRNKIDN, SP_CNCR, SP_COPD, SP_DEPRESSN, SP_DIABETES, SP_ISCHMCHT, SP_OSTEOPRSS, SP_RA_OA, SP_STRKETIA.
  Financials: MEDREIMB_IP, BENRES_IP, PPPYMT_IP, MEDREIMB_OP, BENRES_OP, PPPYMT_OP, MEDREIMB_CAR, BENRES_CAR, PPPYMT_CAR.

**carrier_claims** / **new_carrier_claims** (142 cols each):
  Key: CLM_ID (BIGINT old / VARCHAR new), DESYNPUF_ID.
  Dates: CLM_FROM_DT, CLM_THRU_DT.
  Diagnoses: ICD9_DGNS_CD_1..8. Provider NPIs: PRF_PHYSN_NPI_1..13.
  HCPCS: HCPCS_CD_1..13, LINE_CMS_TYPE_SRVC_CD_1..13, LINE_PLACE_OF_SRVC_CD_1..13.
  **Payment columns are line-level ONLY (no claim-level totals):**
    LINE_NCH_PMT_AMT_1..13, LINE_BENE_PTB_DDCTBL_AMT_1..13,
    LINE_BENE_PRMRY_PYR_PD_AMT_1..13, LINE_COINSRNC_AMT_1..13, LINE_ALOWD_CHRG_AMT_1..13.
  Both old and new tables share identical column names.

**_discrepancy_detail** (37 cols): Per-beneficiary diffs. diff_* (1=mismatch), delta_* (dollars), total_diffs.
**_financial_recon** (11 cols): reported_* vs calc_* with *_diff columns.
**_match_beneficiary** / **_match_claims**: match_status (matched/old_only/new_only).

### Important SQL Notes
- NEVER use `new` or `old` as table aliases — they are reserved keywords in DuckDB. Use `oc`/`nc` or `old_claims`/`new_claims`.
- "ZZ" prefix on DESYNPUF_ID = fabricated test records from new system.
- Join old/new claims: `carrier_claims oc JOIN new_carrier_claims nc ON oc.CLM_ID::VARCHAR = nc.CLM_ID`
- 0.90 payment ratio pattern: new payments = old * 0.90.
- Use DESCRIBE tablename or SELECT * FROM information_schema.columns WHERE table_name='...' to discover columns if unsure.

## Guidelines
1. Be concise and data-driven. Query the database to verify claims.
2. **Always explain your SQL queries** — what they do and what the results mean.
3. Summarize results in markdown tables when appropriate.
4. Explain technical terms (ICD-9, HCPCS, NPI, etc.) in plain language.
"""

_LAMBDA_TOOL = {
    "type": "function",
    "function": {
        "name": "query_database",
        "description": "Execute a read-only SQL SELECT query against the CMS claims DuckDB database. Always include LIMIT (max 50).",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SQL SELECT query to execute."},
                "explanation": {"type": "string", "description": "Plain-English explanation of what this query does, why you are running it, and what the results will tell us."}
            },
            "required": ["sql", "explanation"]
        }
    }
}


def handle_chat(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for AI chat — triggered by API Gateway POST /api/chat.

    Reads OpenAI key from SSM, downloads DuckDB from S3, runs function-calling
    loop with query_database tool.
    """
    import openai as openai_mod

    # Parse API Gateway event
    body = event.get("body", "{}")
    if isinstance(body, str):
        body = json.loads(body)

    message = body.get("message", "").strip()
    conversation_history = body.get("conversationHistory", [])
    model = body.get("model", "gpt-4o")

    if not message:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": "message is required"}),
        }

    try:
        api_key = _get_openai_api_key()
        db_con = _ensure_db_ready(event)
    except Exception as e:
        logger.exception("Chat setup failed")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": str(e)}),
        }

    # Build system prompt
    findings = _build_chat_findings(db_con)
    system_prompt = _LAMBDA_SYSTEM_PROMPT.format(findings_context=findings)

    messages = [
        {"role": "system", "content": system_prompt},
        *[{"role": m["role"], "content": m["content"]} for m in conversation_history],
        {"role": "user", "content": message},
    ]

    try:
        client = openai_mod.OpenAI(api_key=api_key)
        tools = [_LAMBDA_TOOL]
        sql_queries_run = []

        for _round in range(_MAX_TOOL_ROUNDS):
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                max_tokens=2000,
                temperature=0.4,
            )

            choice = response.choices[0]

            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                content = choice.message.content or ""
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
                    "body": json.dumps({
                        "content": content,
                        "model": response.model or model,
                        "queries": sql_queries_run,
                    }),
                }

            messages.append(choice.message)

            for tool_call in choice.message.tool_calls:
                if tool_call.function.name == "query_database":
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        args = {"sql": ""}

                    sql = args.get("sql", "")
                    explanation = args.get("explanation", "")
                    logger.info(f"[chat] SQL: {sql[:200]}")

                    result = _chat_execute_query(db_con, sql)
                    sql_queries_run.append({
                        "sql": sql,
                        "explanation": explanation,
                        "result_preview": {
                            "columns": result.get("columns", []),
                            "row_count": result.get("row_count", 0),
                            "truncated": result.get("truncated", False),
                            "error": result.get("error"),
                        }
                    })

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, default=str),
                    })
                else:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps({"error": f"Unknown tool: {tool_call.function.name}"}),
                    })

        # Exhausted tool rounds — final answer
        response = client.chat.completions.create(
            model=model, messages=messages, max_tokens=2000, temperature=0.4,
        )
        content = response.choices[0].message.content or ""
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
            "body": json.dumps({
                "content": content,
                "model": response.model or model,
                "queries": sql_queries_run,
            }),
        }

    except Exception as e:
        logger.exception("Chat API error")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": f"Chat failed: {str(e)}"}),
        }
