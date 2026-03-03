"""
STEP 4: RECORD MATCHING — Match old system records to new system records by key.

Responsibilities:
  - Match beneficiaries by DESYNPUF_ID + summary_year
  - Match claims by CLM_ID
  - Classify every record: matched, old_only, new_only
  - Create match tables in DuckDB for downstream comparison
  - Run internal consistency checks (from validate.py) on both systems
"""

import logging

import duckdb

from src.pipeline import PipelineContext, StepResult
from src.validate import run as validate_run

logger = logging.getLogger(__name__)

MATCH_CONFIGS = [
    {
        "old_table": "beneficiary_summary",
        "new_table": "new_beneficiary_summary",
        "key_cols": ["DESYNPUF_ID", "summary_year"],
        "match_table": "_match_beneficiary",
    },
    {
        "old_table": "carrier_claims",
        "new_table": "new_carrier_claims",
        "key_cols": ["CLM_ID"],
        "match_table": "_match_claims",
    },
]


def _table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    r = con.execute(
        f"SELECT COUNT(*) FROM information_schema.tables "
        f"WHERE table_schema='main' AND table_name='{table_name}'"
    ).fetchone()
    return r[0] > 0


def _build_match_table(
    con: duckdb.DuckDBPyConnection,
    old_table: str,
    new_table: str,
    key_cols: list[str],
    match_table: str,
) -> dict:
    """Create a match table classifying records as matched/old_only/new_only."""
    key_join = " AND ".join(f"o.{k} = n.{k}" for k in key_cols)
    key_select = ", ".join(f"COALESCE(o.{k}, n.{k}) AS {k}" for k in key_cols)
    old_null_check = f"o.{key_cols[0]} IS NULL"
    new_null_check = f"n.{key_cols[0]} IS NULL"

    con.execute(f"DROP TABLE IF EXISTS {match_table}")
    con.execute(f"""
        CREATE TABLE {match_table} AS
        SELECT
            {key_select},
            CASE
                WHEN {old_null_check} THEN 'new_only'
                WHEN {new_null_check} THEN 'old_only'
                ELSE 'matched'
            END AS match_status
        FROM {old_table} o
        FULL OUTER JOIN {new_table} n ON {key_join}
    """)

    # Count by status
    counts = {}
    for row in con.execute(f"""
        SELECT match_status, COUNT(*) FROM {match_table} GROUP BY match_status
    """).fetchall():
        counts[row[0]] = row[1]

    total = sum(counts.values())
    return {
        "match_table": match_table,
        "total_records": total,
        "matched": counts.get("matched", 0),
        "old_only": counts.get("old_only", 0),
        "new_only": counts.get("new_only", 0),
        "match_rate": round(100.0 * counts.get("matched", 0) / max(total, 1), 2),
    }


def run(ctx: PipelineContext) -> StepResult:
    """Execute Step 4: Record matching and internal validation."""
    con = ctx.con
    errors = []
    warnings = []
    match_results = {}

    # Internal consistency checks on old system (always)
    validations = validate_run(con)
    ctx.results["validations"] = validations

    passed = sum(1 for v in validations if v.passed)
    failed = len(validations) - passed
    if failed > 0:
        warnings.append(f"{failed} internal consistency check(s) failed on old system")

    # Record matching (only if new system data exists)
    has_new_data = False
    for cfg in MATCH_CONFIGS:
        if not _table_exists(con, cfg["new_table"]):
            logger.info(f"Skipping match for {cfg['old_table']} — new table not loaded")
            continue

        has_new_data = True
        logger.info(f"Matching {cfg['old_table']} ↔ {cfg['new_table']}...")
        result = _build_match_table(
            con, cfg["old_table"], cfg["new_table"],
            cfg["key_cols"], cfg["match_table"],
        )
        match_results[cfg["old_table"]] = result

        logger.info(
            f"  {result['matched']:,} matched, "
            f"{result['old_only']:,} old-only, "
            f"{result['new_only']:,} new-only "
            f"({result['match_rate']}% match rate)"
        )

        if result["old_only"] > 0:
            warnings.append(
                f"{result['old_only']:,} {cfg['old_table']} records missing in new system"
            )
        if result["new_only"] > 0:
            warnings.append(
                f"{result['new_only']:,} extra {cfg['old_table']} records in new system"
            )

    ctx.results["match"] = {
        "match_results": match_results,
        "has_new_data": has_new_data,
        "validation_passed": passed,
        "validation_failed": failed,
        "validation_total": len(validations),
    }

    msg_parts = [f"Validation: {passed}/{len(validations)} passed"]
    if has_new_data:
        for table, r in match_results.items():
            msg_parts.append(f"{table}: {r['match_rate']}% matched")
    else:
        msg_parts.append("No new system data for matching")

    return StepResult(
        step_name="match",
        success=True,
        message=". ".join(msg_parts),
        data=ctx.results["match"],
        errors=errors,
        warnings=warnings,
    )
