"""
STEP 5: COMPARE — Field-level diffs, discrepancy classification, trend analysis.

Responsibilities:
  - For matched records: field-by-field comparison
  - Classify discrepancies by type (financial, demographic, clinical, temporal)
  - Compute aggregate divergence metrics
  - Identify trends: by year, by state, by condition
  - Build summary tables for the report
"""

import logging

import duckdb

from src.pipeline import PipelineContext, StepResult
from src.compare import run as compare_run

logger = logging.getLogger(__name__)


def _table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    r = con.execute(
        f"SELECT COUNT(*) FROM information_schema.tables "
        f"WHERE table_schema='main' AND table_name='{table_name}'"
    ).fetchone()
    return r[0] > 0


def _build_discrepancy_detail(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """
    For matched beneficiary records, compute per-field diffs and classify them.
    Creates a _discrepancy_detail table for trend analysis.
    """
    if not _table_exists(con, "new_beneficiary_summary"):
        return []

    # Financial columns
    financial_cols = [
        "MEDREIMB_IP", "BENRES_IP", "PPPYMT_IP",
        "MEDREIMB_OP", "BENRES_OP", "PPPYMT_OP",
        "MEDREIMB_CAR", "BENRES_CAR", "PPPYMT_CAR",
    ]
    # Demographic columns
    demo_cols = ["BENE_SEX_IDENT_CD", "BENE_RACE_CD", "BENE_BIRTH_DT", "BENE_DEATH_DT"]
    # Clinical columns
    clinical_cols = [
        "SP_ALZHDMTA", "SP_CHF", "SP_CHRNKIDN", "SP_CNCR", "SP_COPD",
        "SP_DEPRESSN", "SP_DIABETES", "SP_ISCHMCHT", "SP_OSTEOPRS",
        "SP_RA_OA", "SP_STRKETIA",
    ]

    all_cols = financial_cols + demo_cols + clinical_cols

    # Build per-row discrepancy flags
    diff_exprs = []
    for col in all_cols:
        diff_exprs.append(
            f"CASE WHEN o.\"{col}\"::VARCHAR IS DISTINCT FROM n.\"{col}\"::VARCHAR "
            f"THEN 1 ELSE 0 END AS diff_{col.lower()}"
        )

    # Dollar impact for financial columns
    dollar_exprs = []
    for col in financial_cols:
        dollar_exprs.append(
            f"COALESCE(ABS(o.\"{col}\"::DOUBLE - n.\"{col}\"::DOUBLE), 0) AS delta_{col.lower()}"
        )

    try:
        con.execute("DROP TABLE IF EXISTS _discrepancy_detail")
        con.execute(f"""
            CREATE TABLE _discrepancy_detail AS
            SELECT
                o.DESYNPUF_ID,
                o.summary_year,
                o.SP_STATE_CODE,
                {', '.join(diff_exprs)},
                {', '.join(dollar_exprs)},
                ({' + '.join(f'diff_{c.lower()}' for c in all_cols)}) AS total_diffs
            FROM beneficiary_summary o
            INNER JOIN new_beneficiary_summary n
                ON o.DESYNPUF_ID = n.DESYNPUF_ID
                AND o.summary_year = n.summary_year
        """)

        # Compute trend summaries
        trends = []

        # Overall mismatch rate
        r = con.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN total_diffs > 0 THEN 1 ELSE 0 END) AS mismatched
            FROM _discrepancy_detail
        """).fetchone()
        trends.append({
            "trend": "overall_mismatch_rate",
            "total": r[0],
            "affected": r[1],
            "rate_pct": round(100.0 * r[1] / max(r[0], 1), 2),
        })

        # Mismatch by year
        for row in con.execute("""
            SELECT summary_year, COUNT(*), SUM(CASE WHEN total_diffs > 0 THEN 1 ELSE 0 END)
            FROM _discrepancy_detail
            GROUP BY summary_year ORDER BY summary_year
        """).fetchall():
            trends.append({
                "trend": f"mismatch_by_year_{row[0]}",
                "year": row[0],
                "total": row[1],
                "affected": row[2],
                "rate_pct": round(100.0 * row[2] / max(row[1], 1), 2),
            })

        # Financial impact by year
        for row in con.execute(f"""
            SELECT
                summary_year,
                SUM({' + '.join(f'delta_{c.lower()}' for c in financial_cols)}) AS total_dollar_impact
            FROM _discrepancy_detail
            GROUP BY summary_year ORDER BY summary_year
        """).fetchall():
            trends.append({
                "trend": f"financial_impact_{row[0]}",
                "year": row[0],
                "dollar_impact": round(row[1], 2),
            })

        # Most affected fields
        for col in all_cols:
            r = con.execute(f"""
                SELECT SUM(diff_{col.lower()}) FROM _discrepancy_detail
            """).fetchone()
            if r[0] and r[0] > 0:
                trends.append({
                    "trend": "field_mismatch_count",
                    "field": col,
                    "mismatches": r[0],
                })

        return trends

    except Exception as e:
        logger.warning(f"Could not build discrepancy detail: {e}")
        return []


def run(ctx: PipelineContext) -> StepResult:
    """Execute Step 5: Comparison and trend analysis."""
    con = ctx.con
    errors = []
    warnings = []

    # Run the existing comparison engine
    comparisons = compare_run(con)
    ctx.results["comparisons"] = comparisons

    # Build detailed discrepancy analysis
    trends = _build_discrepancy_detail(con)
    ctx.results["trends"] = trends

    # Compute summary metrics
    has_new = len(comparisons) > 0
    overall_trend = next((t for t in trends if t["trend"] == "overall_mismatch_rate"), None)

    msg_parts = [f"{len(comparisons)} comparison checks"]
    if overall_trend:
        msg_parts.append(
            f"{overall_trend['affected']:,}/{overall_trend['total']:,} "
            f"beneficiaries mismatched ({overall_trend['rate_pct']}%)"
        )
        financial_impacts = [t for t in trends if t["trend"].startswith("financial_impact_")]
        if financial_impacts:
            total_impact = sum(t.get("dollar_impact", 0) for t in financial_impacts)
            msg_parts.append(f"${total_impact:,.2f} total financial divergence")
    elif not has_new:
        msg_parts.append("No new system data — comparison skipped")

    ctx.results["compare"] = {
        "comparison_count": len(comparisons),
        "has_new_data": has_new,
        "trends": trends,
    }

    return StepResult(
        step_name="compare",
        success=True,
        message=". ".join(msg_parts),
        data=ctx.results["compare"],
        errors=errors,
        warnings=warnings,
    )
