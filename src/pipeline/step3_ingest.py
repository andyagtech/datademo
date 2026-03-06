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


def _claim_line_utilization(con: duckdb.DuckDBPyConnection) -> dict:
    """Analyze how many claim lines are populated per carrier claim.

    Each carrier claim can have up to 13 service lines. Understanding the
    distribution (e.g., "85% of claims use ≤3 lines") reveals the typical
    claim complexity and helps validate that multi-line payment aggregation
    logic handles the actual data shape.
    """
    try:
        # Count non-null payment lines per claim (LINE_NCH_PMT_AMT_1 .. _13)
        line_count_expr = " + ".join(
            f"CASE WHEN LINE_NCH_PMT_AMT_{i} IS NOT NULL THEN 1 ELSE 0 END"
            for i in range(1, 14)
        )
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE _line_counts AS
            SELECT CLM_ID, ({line_count_expr}) AS populated_lines
            FROM carrier_claims
        """)

        total_claims = con.execute("SELECT COUNT(*) FROM _line_counts").fetchone()[0]

        # Distribution buckets
        dist = con.execute("""
            SELECT populated_lines, COUNT(*) AS cnt
            FROM _line_counts
            GROUP BY populated_lines
            ORDER BY populated_lines
        """).fetchall()
        distribution = {row[0]: row[1] for row in dist}

        # Summary statistics
        stats = con.execute("""
            SELECT
                AVG(populated_lines),
                MEDIAN(populated_lines),
                MAX(populated_lines),
                SUM(CASE WHEN populated_lines <= 1 THEN 1 ELSE 0 END),
                SUM(CASE WHEN populated_lines <= 3 THEN 1 ELSE 0 END),
                SUM(CASE WHEN populated_lines <= 5 THEN 1 ELSE 0 END)
            FROM _line_counts
        """).fetchone()

        return {
            "total_claims": total_claims,
            "avg_lines": round(stats[0], 2) if stats[0] else 0,
            "median_lines": int(stats[1]) if stats[1] else 0,
            "max_lines": int(stats[2]) if stats[2] else 0,
            "pct_single_line": round(100.0 * stats[3] / max(total_claims, 1), 1),
            "pct_lte_3_lines": round(100.0 * stats[4] / max(total_claims, 1), 1),
            "pct_lte_5_lines": round(100.0 * stats[5] / max(total_claims, 1), 1),
            "distribution": distribution,
        }
    except duckdb.Error as e:
        logger.warning(f"Claim line utilization analysis failed: {e}")
        return {}


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

    # Claim line utilization analysis
    line_util = _claim_line_utilization(con)
    ctx.results["claim_line_utilization"] = line_util
    if line_util:
        logger.info(
            f"  Claim line utilization: avg={line_util['avg_lines']} lines/claim, "
            f"median={line_util['median_lines']}, "
            f"{line_util['pct_lte_3_lines']}% use ≤3 lines"
        )

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
        "claim_line_utilization": line_util,
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
