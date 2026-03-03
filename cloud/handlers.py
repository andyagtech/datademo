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
    """Lambda handler for Step 2: Schema Validation."""
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
    """Lambda handler for Step 4: Record Matching."""
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
