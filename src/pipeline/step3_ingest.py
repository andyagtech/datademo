"""
STEP 3: INGEST & PROFILE — Load CSVs into DuckDB and profile data quality.

Responsibilities:
  - Load old system CSVs into DuckDB tables
  - Load new system CSVs (if available) into prefixed tables
  - Run column-level profiling (nulls, types, distributions)
  - Flag anomalies: impossible values, out-of-range dates, negative payments
"""

import logging
from pathlib import Path

import duckdb

from src.pipeline import PipelineContext, StepResult
from src.ingest import (
    ingest_beneficiary_summaries,
    ingest_carrier_claims,
    ingest_new_system,
    get_connection,
    DB_PATH,
)
from src.profile import run as profile_run

logger = logging.getLogger(__name__)


def _detect_anomalies(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Run quick anomaly detection on ingested data."""
    anomalies = []

    # Negative payment amounts
    for col in ["MEDREIMB_CAR", "BENRES_CAR", "PPPYMT_CAR",
                "MEDREIMB_IP", "BENRES_IP", "PPPYMT_IP",
                "MEDREIMB_OP", "BENRES_OP", "PPPYMT_OP"]:
        try:
            r = con.execute(f"""
                SELECT COUNT(*) FROM beneficiary_summary WHERE {col} < 0
            """).fetchone()
            if r[0] > 0:
                anomalies.append({
                    "type": "negative_payment",
                    "table": "beneficiary_summary",
                    "column": col,
                    "count": r[0],
                    "severity": "high",
                })
        except duckdb.Error as e:
            logger.debug(f"Anomaly check skipped for {col}: {e}")

    # Future birth dates (BENE_BIRTH_DT > 20250101)
    try:
        r = con.execute("""
            SELECT COUNT(*) FROM beneficiary_summary
            WHERE BENE_BIRTH_DT > 20250101
        """).fetchone()
        if r[0] > 0:
            anomalies.append({
                "type": "future_birth_date",
                "table": "beneficiary_summary",
                "column": "BENE_BIRTH_DT",
                "count": r[0],
                "severity": "high",
            })
    except duckdb.Error as e:
        logger.debug(f"Anomaly check skipped for BENE_BIRTH_DT: {e}")

    # Invalid sex codes (should be 1 or 2)
    try:
        r = con.execute("""
            SELECT COUNT(*) FROM beneficiary_summary
            WHERE BENE_SEX_IDENT_CD NOT IN (1, 2)
        """).fetchone()
        if r[0] > 0:
            anomalies.append({
                "type": "invalid_sex_code",
                "table": "beneficiary_summary",
                "column": "BENE_SEX_IDENT_CD",
                "count": r[0],
                "severity": "medium",
            })
    except duckdb.Error as e:
        logger.debug(f"Anomaly check skipped for BENE_SEX_IDENT_CD: {e}")

    # Claims with zero or negative payment across all lines
    try:
        r = con.execute("""
            SELECT COUNT(*) FROM carrier_claims
            WHERE COALESCE(LINE_NCH_PMT_AMT_1, 0) +
                  COALESCE(LINE_NCH_PMT_AMT_2, 0) +
                  COALESCE(LINE_NCH_PMT_AMT_3, 0) +
                  COALESCE(LINE_NCH_PMT_AMT_4, 0) +
                  COALESCE(LINE_NCH_PMT_AMT_5, 0) +
                  COALESCE(LINE_NCH_PMT_AMT_6, 0) +
                  COALESCE(LINE_NCH_PMT_AMT_7, 0) +
                  COALESCE(LINE_NCH_PMT_AMT_8, 0) +
                  COALESCE(LINE_NCH_PMT_AMT_9, 0) +
                  COALESCE(LINE_NCH_PMT_AMT_10, 0) +
                  COALESCE(LINE_NCH_PMT_AMT_11, 0) +
                  COALESCE(LINE_NCH_PMT_AMT_12, 0) +
                  COALESCE(LINE_NCH_PMT_AMT_13, 0) <= 0
        """).fetchone()
        if r[0] > 0:
            anomalies.append({
                "type": "zero_total_payment",
                "table": "carrier_claims",
                "column": "LINE_NCH_PMT_AMT_*",
                "count": r[0],
                "severity": "medium",
            })
    except duckdb.Error as e:
        logger.debug(f"Anomaly check skipped for zero_total_payment: {e}")

    return anomalies


def run(ctx: PipelineContext) -> StepResult:
    """Execute Step 3: Ingest into DuckDB and profile."""
    errors: list[str] = []
    warnings: list[str] = []

    # Get or create DB connection
    if ctx.skip_ingest and ctx.con:
        con = ctx.con
        logger.info("Reusing existing DB connection (skip_ingest=True)")
    elif ctx.skip_ingest:
        db_path = ctx.db_path or DB_PATH
        if not db_path.exists():
            return StepResult(
                step_name="ingest",
                success=False,
                message=f"Database not found at {db_path}. Run without --skip-ingest.",
                errors=[f"DB not found: {db_path}"],
            )
        con = get_connection(db_path)
        ctx.con = con
        logger.info(f"Connected to existing DB: {db_path}")
    else:
        db_path = ctx.db_path or DB_PATH
        con = get_connection(db_path)
        ctx.con = con

        try:
            ingest_beneficiary_summaries(con)
            ingest_carrier_claims(con)
        except (FileNotFoundError, ValueError) as e:
            return StepResult(
                step_name="ingest",
                success=False,
                message=str(e),
                errors=[str(e)],
            )

        # Ingest new system if available
        if ctx.new_data_dir:
            new_dir = ctx.new_data_dir
            if new_dir.is_file() and new_dir.suffix == ".zip":
                new_dir = new_dir.parent / "new_system_extracted"
            if new_dir.is_dir():
                ingest_new_system(con, new_dir)

    # Profile
    profiles = profile_run(con)
    ctx.results["profiles"] = profiles

    # Anomaly detection
    anomalies = _detect_anomalies(con)
    ctx.results["anomalies"] = anomalies
    if anomalies:
        high = [a for a in anomalies if a["severity"] == "high"]
        if high:
            warnings.append(f"{len(high)} high-severity anomalies detected")

    # Counts
    try:
        bene_count = con.execute("SELECT COUNT(*) FROM beneficiary_summary").fetchone()[0]
        claim_count = con.execute("SELECT COUNT(*) FROM carrier_claims").fetchone()[0]
    except duckdb.Error as e:
        logger.warning(f"Could not query row counts: {e}")
        bene_count = 0
        claim_count = 0

    ctx.results["ingest"] = {
        "beneficiary_count": bene_count,
        "claims_count": claim_count,
        "anomalies": anomalies,
        "tables_profiled": len(profiles),
    }

    return StepResult(
        step_name="ingest",
        success=True,
        message=f"Ingested {bene_count:,} beneficiaries, {claim_count:,} claims. "
                f"Profiled {len(profiles)} tables. {len(anomalies)} anomalies.",
        data=ctx.results["ingest"],
        errors=errors,
        warnings=warnings,
    )
