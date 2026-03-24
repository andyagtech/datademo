"""
REPORT stage — Generate an HTML report from profiling, validation, and comparison results.

Uses Jinja2 for templating and Plotly for interactive charts.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import duckdb
import plotly.graph_objects as go
import plotly.io as pio

from src.profile import TableProfile
from src.validate import ValidationResult
from src.compare import ComparisonResult
from src.chat_answers import generate_cached_answers

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).resolve().parent.parent / "reports"
TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "report.html.j2"

HTML_TEMPLATE = TEMPLATE_PATH.read_text(encoding="utf-8")



def _build_yoy_beneficiary_chart(con: duckdb.DuckDBPyConnection) -> str:
    """Beneficiary count by summary year."""
    try:
        rows = con.execute("""
            SELECT summary_year, COUNT(*) AS cnt
            FROM beneficiary_summary
            GROUP BY summary_year ORDER BY summary_year
        """).fetchall()
    except Exception:
        return ""
    if not rows:
        return ""

    years = [str(r[0]) for r in rows]
    counts = [r[1] for r in rows]

    fig = go.Figure(go.Bar(
        x=years, y=counts,
        marker_color="#38bdf8",
        text=[f"{c:,}" for c in counts],
        textposition="outside",
    ))
    fig.update_layout(
        title="Beneficiaries by Year",
        plot_bgcolor="#1e293b", paper_bgcolor="#1e293b",
        font=dict(color="#e2e8f0", size=11),
        xaxis=dict(title="Year", gridcolor="#334155"),
        yaxis=dict(title="Count", gridcolor="#334155"),
        height=350, margin=dict(l=60, r=30, t=50, b=40),
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


def _build_yoy_claims_chart(con: duckdb.DuckDBPyConnection) -> str:
    """Carrier claims volume by year."""
    try:
        rows = con.execute("""
            SELECT (CLM_FROM_DT / 10000)::INT AS yr, COUNT(*) AS cnt
            FROM carrier_claims
            GROUP BY yr ORDER BY yr
        """).fetchall()
    except Exception:
        return ""
    if not rows:
        return ""

    years = [str(r[0]) for r in rows]
    counts = [r[1] for r in rows]

    fig = go.Figure(go.Bar(
        x=years, y=counts,
        marker_color="#a78bfa",
        text=[f"{c:,}" for c in counts],
        textposition="outside",
    ))
    fig.update_layout(
        title="Carrier Claims by Year",
        plot_bgcolor="#1e293b", paper_bgcolor="#1e293b",
        font=dict(color="#e2e8f0", size=11),
        xaxis=dict(title="Year", gridcolor="#334155"),
        yaxis=dict(title="Claims", gridcolor="#334155"),
        height=350, margin=dict(l=60, r=30, t=50, b=40),
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


def _build_financial_trends_chart(con: duckdb.DuckDBPyConnection) -> str:
    """Stacked bar chart of reimbursement totals by year (IP, OP, CAR)."""
    try:
        rows = con.execute("""
            SELECT
                summary_year,
                SUM(MEDREIMB_IP) AS ip_total,
                SUM(MEDREIMB_OP) AS op_total,
                SUM(MEDREIMB_CAR) AS car_total
            FROM beneficiary_summary
            GROUP BY summary_year ORDER BY summary_year
        """).fetchall()
    except Exception:
        return ""
    if not rows:
        return ""

    years = [str(r[0]) for r in rows]
    ip = [r[1] for r in rows]
    op = [r[2] for r in rows]
    car = [r[3] for r in rows]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Inpatient", x=years, y=ip, marker_color="#f87171"))
    fig.add_trace(go.Bar(name="Outpatient", x=years, y=op, marker_color="#fbbf24"))
    fig.add_trace(go.Bar(name="Carrier", x=years, y=car, marker_color="#4ade80"))
    fig.update_layout(
        barmode="group",
        title="Medicare Reimbursement Totals by Year & Type",
        plot_bgcolor="#1e293b", paper_bgcolor="#1e293b",
        font=dict(color="#e2e8f0", size=11),
        xaxis=dict(title="Year", gridcolor="#334155"),
        yaxis=dict(title="Total Reimbursement ($)", gridcolor="#334155"),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        height=400, margin=dict(l=80, r=30, t=50, b=40),
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


def _build_financial_distribution_chart(con: duckdb.DuckDBPyConnection) -> str:
    """Box plots of carrier reimbursement amounts across beneficiaries."""
    try:
        data = con.execute("""
            SELECT MEDREIMB_CAR, BENRES_CAR, PPPYMT_CAR
            FROM beneficiary_summary
            WHERE MEDREIMB_CAR > 0
            USING SAMPLE 5000
        """).fetchdf()
    except Exception:
        return ""
    if data.empty:
        return ""

    fig = go.Figure()
    fig.add_trace(go.Box(y=data["MEDREIMB_CAR"], name="Medicare Reimb", marker_color="#4ade80"))
    fig.add_trace(go.Box(y=data["BENRES_CAR"], name="Beneficiary Resp", marker_color="#fbbf24"))
    fig.add_trace(go.Box(y=data["PPPYMT_CAR"], name="Primary Payer", marker_color="#38bdf8"))
    fig.update_layout(
        title="Carrier Payment Distribution (sample)",
        plot_bgcolor="#1e293b", paper_bgcolor="#1e293b",
        font=dict(color="#e2e8f0", size=11),
        yaxis=dict(title="Amount ($)", gridcolor="#334155"),
        showlegend=False,
        height=400, margin=dict(l=80, r=30, t=50, b=40),
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


def _build_chronic_conditions_chart(con: duckdb.DuckDBPyConnection) -> str:
    """Chronic condition prevalence by year."""
    conditions = [
        ("SP_ALZHDMTA", "Alzheimer's"), ("SP_CHF", "Heart Failure"),
        ("SP_CHRNKIDN", "Kidney Disease"), ("SP_CNCR", "Cancer"),
        ("SP_COPD", "COPD"), ("SP_DEPRESSN", "Depression"),
        ("SP_DIABETES", "Diabetes"), ("SP_ISCHMCHT", "Ischemic Heart"),
        ("SP_OSTEOPRS", "Osteoporosis"), ("SP_RA_OA", "RA/OA"),
        ("SP_STRKETIA", "Stroke/TIA"),
    ]
    try:
        years_rows = con.execute(
            "SELECT DISTINCT summary_year FROM beneficiary_summary ORDER BY summary_year"
        ).fetchall()
        years = [r[0] for r in years_rows]
    except Exception:
        return ""
    if not years:
        return ""

    fig = go.Figure()
    colors = ["#f87171", "#fb923c", "#fbbf24", "#a3e635", "#4ade80",
              "#2dd4bf", "#38bdf8", "#818cf8", "#a78bfa", "#f472b6", "#e2e8f0"]

    for idx, (col, label) in enumerate(conditions):
        rates = []
        for yr in years:
            try:
                r = con.execute(f"""
                    SELECT ROUND(100.0 * SUM(CASE WHEN {col} = 1 THEN 1 ELSE 0 END) / COUNT(*), 1)
                    FROM beneficiary_summary WHERE summary_year = {yr}
                """).fetchone()
                rates.append(r[0] if r[0] else 0)
            except Exception:
                rates.append(0)
        fig.add_trace(go.Scatter(
            x=[str(y) for y in years], y=rates,
            mode="lines+markers", name=label,
            line=dict(color=colors[idx % len(colors)], width=2),
            marker=dict(size=6),
        ))

    fig.update_layout(
        title="Chronic Condition Prevalence by Year (%)",
        plot_bgcolor="#1e293b", paper_bgcolor="#1e293b",
        font=dict(color="#e2e8f0", size=11),
        xaxis=dict(title="Year", gridcolor="#334155"),
        yaxis=dict(title="Prevalence (%)", gridcolor="#334155"),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=10)),
        height=400, margin=dict(l=60, r=30, t=50, b=40),
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


def _build_validation_chart(validations: list[ValidationResult]) -> str:
    """Create a horizontal bar chart of validation results."""
    checks = [v.check_name for v in validations]
    issues = [v.issues_found for v in validations]
    colors = ["#f87171" if v.issues_found > 0 else "#4ade80" for v in validations]

    fig = go.Figure(go.Bar(
        x=issues,
        y=checks,
        orientation="h",
        marker_color=colors,
        text=[f"{i:,}" for i in issues],
        textposition="outside",
    ))
    fig.update_layout(
        title="Issues Found Per Validation Check",
        plot_bgcolor="#1e293b",
        paper_bgcolor="#1e293b",
        font=dict(color="#e2e8f0", size=11),
        xaxis=dict(title="Issues Found", gridcolor="#334155"),
        yaxis=dict(autorange="reversed", gridcolor="#334155"),
        height=max(350, len(checks) * 35),
        margin=dict(l=250, r=60, t=50, b=40),
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


def _serialize_profile(profile: TableProfile) -> dict[str, object]:
    """Convert a TableProfile to a dict for template rendering."""
    high_null = sum(1 for c in profile.columns if c.null_pct > 50)
    return {
        "row_count": f"{profile.row_count:,}",
        "column_count": profile.column_count,
        "high_null_cols": high_null,
        "columns": [
            {
                "name": c.name,
                "dtype": c.dtype,
                "null_count": f"{c.null_count:,}",
                "null_pct": c.null_pct,
                "distinct_count": f"{c.distinct_count:,}",
                "min_val": c.min_val,
                "max_val": c.max_val,
                "mean_val": c.mean_val,
            }
            for c in profile.columns
        ],
    }


def _build_file_inventory(inventory: dict) -> list[dict]:
    """Convert a receive-step inventory dict to a list for template rendering."""
    files = []
    for name, info in sorted(inventory.items()):
        files.append({
            "name": name,
            "rows": f"{info.get('row_count', '—'):,}" if isinstance(info.get('row_count'), int) else info.get('row_count', '—'),
            "size": f"{info.get('size_mb', 0):.1f} MB",
        })
    return files


def _count_rows_for_inventory(con: duckdb.DuckDBPyConnection, inventory: dict) -> dict:
    """Enrich file inventory with row counts by reading the CSVs via DuckDB."""
    enriched = {}
    for name, info in inventory.items():
        path = info.get("path", "")
        row_count = "—"
        if path:
            try:
                r = con.execute(f"SELECT COUNT(*) FROM read_csv_auto('{path}', header=true)").fetchone()
                row_count = r[0]
            except Exception:
                pass
        enriched[name] = {**info, "row_count": row_count}
    return enriched


def _extract_chart_data(con: duckdb.DuckDBPyConnection | None) -> dict:
    """Extract raw chart data series from DuckDB for JSON output.

    These are the underlying data points that any presentation layer
    (HTML/Plotly, React, CLI, PDF) can use to render its own charts.
    """
    chart_data: dict = {}
    if not con:
        return chart_data

    # YoY beneficiary counts
    try:
        rows = con.execute("""
            SELECT summary_year, COUNT(*) AS cnt
            FROM beneficiary_summary
            GROUP BY summary_year ORDER BY summary_year
        """).fetchall()
        chart_data["yoy_beneficiaries"] = [
            {"year": int(r[0]), "count": r[1]} for r in rows
        ]
    except Exception:
        pass

    # YoY claims counts
    try:
        rows = con.execute("""
            SELECT (CLM_FROM_DT / 10000)::INT AS yr, COUNT(*) AS cnt
            FROM carrier_claims
            GROUP BY yr ORDER BY yr
        """).fetchall()
        chart_data["yoy_claims"] = [
            {"year": int(r[0]), "count": r[1]} for r in rows
        ]
    except Exception:
        pass

    # Financial trends (reimbursement by year & type)
    try:
        rows = con.execute("""
            SELECT
                summary_year,
                SUM(MEDREIMB_IP) AS ip_total,
                SUM(MEDREIMB_OP) AS op_total,
                SUM(MEDREIMB_CAR) AS car_total
            FROM beneficiary_summary
            GROUP BY summary_year ORDER BY summary_year
        """).fetchall()
        chart_data["financial_trends"] = [
            {"year": int(r[0]), "inpatient": float(r[1]), "outpatient": float(r[2]), "carrier": float(r[3])}
            for r in rows
        ]
    except Exception:
        pass

    # Financial distribution (sampled box plot data)
    try:
        data = con.execute("""
            SELECT MEDREIMB_CAR, BENRES_CAR, PPPYMT_CAR
            FROM beneficiary_summary
            WHERE MEDREIMB_CAR > 0
            USING SAMPLE 5000
        """).fetchdf()
        chart_data["financial_distribution"] = {
            "medicare_reimb": data["MEDREIMB_CAR"].tolist(),
            "beneficiary_resp": data["BENRES_CAR"].tolist(),
            "primary_payer": data["PPPYMT_CAR"].tolist(),
        }
    except Exception:
        pass

    # Chronic condition prevalence by year
    conditions = [
        ("SP_ALZHDMTA", "Alzheimer's"), ("SP_CHF", "Heart Failure"),
        ("SP_CHRNKIDN", "Kidney Disease"), ("SP_CNCR", "Cancer"),
        ("SP_COPD", "COPD"), ("SP_DEPRESSN", "Depression"),
        ("SP_DIABETES", "Diabetes"), ("SP_ISCHMCHT", "Ischemic Heart"),
        ("SP_OSTEOPRS", "Osteoporosis"), ("SP_RA_OA", "RA/OA"),
        ("SP_STRKETIA", "Stroke/TIA"),
    ]
    try:
        years_rows = con.execute(
            "SELECT DISTINCT summary_year FROM beneficiary_summary ORDER BY summary_year"
        ).fetchall()
        years = [int(r[0]) for r in years_rows]

        chronic_data = []
        for col, label in conditions:
            rates = []
            for yr in years:
                try:
                    r = con.execute(f"""
                        SELECT ROUND(100.0 * SUM(CASE WHEN {col} = 1 THEN 1 ELSE 0 END) / COUNT(*), 1)
                        FROM beneficiary_summary WHERE summary_year = {yr}
                    """).fetchone()
                    rates.append(float(r[0]) if r[0] else 0.0)
                except Exception:
                    rates.append(0.0)
            chronic_data.append({"condition": label, "column": col, "rates": rates})

        chart_data["chronic_conditions"] = {"years": years, "conditions": chronic_data}
    except Exception:
        pass

    # ── Discrepancy-focused data (old system = truth, new = under test) ──

    # Beneficiary mismatches by field (from _discrepancy_detail)
    # Schema: diff_* columns are 0/1 flags, delta_* are dollar amounts, total_diffs = count
    try:
        diff_cols = con.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = '_discrepancy_detail'
            AND column_name LIKE 'diff_%'
        """).fetchall()
        if diff_cols:
            field_mismatches = []
            for (col_name,) in diff_cols:
                field = col_name.replace("diff_", "").upper()
                try:
                    r = con.execute(f"""
                        SELECT SUM("{col_name}") FROM _discrepancy_detail
                    """).fetchone()
                    count = int(r[0]) if r[0] else 0
                    if count > 0:
                        field_mismatches.append({"field": field, "mismatch_count": count})
                except Exception:
                    pass
            field_mismatches.sort(key=lambda x: x["mismatch_count"], reverse=True)
            chart_data["field_mismatches"] = field_mismatches
    except Exception:
        pass

    # Discrepancy trend by year (beneficiaries with ANY mismatch per year)
    try:
        rows = con.execute("""
            SELECT summary_year,
                   COUNT(*) AS total,
                   SUM(CASE WHEN total_diffs > 0 THEN 1 ELSE 0 END) AS mismatched
            FROM _discrepancy_detail
            GROUP BY summary_year ORDER BY summary_year
        """).fetchall()
        chart_data["discrepancy_by_year"] = [
            {"year": int(r[0]), "total": r[1], "mismatched": r[2],
             "pct": round(100.0 * r[2] / max(r[1], 1), 2)}
            for r in rows
        ]
    except Exception:
        pass

    # Old vs new volume comparison (beneficiaries + claims)
    try:
        for old_t, new_t, label in [
            ("beneficiary_summary", "new_beneficiary_summary", "beneficiaries"),
            ("carrier_claims", "new_carrier_claims", "claims"),
        ]:
            old_count = con.execute(f"SELECT COUNT(*) FROM {old_t}").fetchone()[0]
            try:
                new_count = con.execute(f"SELECT COUNT(*) FROM {new_t}").fetchone()[0]
            except Exception:
                new_count = 0
            chart_data[f"volume_{label}"] = {"old": old_count, "new": new_count, "diff": new_count - old_count}
    except Exception:
        pass

    # Financial divergence summary (old vs new reimbursement totals)
    try:
        for old_t, new_t, label in [
            ("beneficiary_summary", "new_beneficiary_summary", "beneficiary"),
        ]:
            fin_cols = ["MEDREIMB_IP", "BENRES_IP", "PPPYMT_IP",
                        "MEDREIMB_OP", "BENRES_OP", "PPPYMT_OP",
                        "MEDREIMB_CAR", "BENRES_CAR", "PPPYMT_CAR"]
            fin_divergence = []
            for col in fin_cols:
                try:
                    old_sum = con.execute(f'SELECT COALESCE(SUM("{col}"::DOUBLE), 0) FROM {old_t}').fetchone()[0]
                    new_sum = con.execute(f'SELECT COALESCE(SUM("{col}"::DOUBLE), 0) FROM {new_t}').fetchone()[0]
                    diff = new_sum - old_sum
                    fin_divergence.append({
                        "column": col, "old_sum": round(old_sum, 2), "new_sum": round(new_sum, 2),
                        "diff": round(diff, 2), "abs_diff": round(abs(diff), 2),
                    })
                except Exception:
                    pass
            chart_data["financial_divergence"] = fin_divergence
    except Exception:
        pass

    # Claims payment mismatches (from new vs old on matched claims)
    try:
        pmt_cols = [
                    "LINE_NCH_PMT_AMT_1", "LINE_NCH_PMT_AMT_2", "LINE_NCH_PMT_AMT_3",
                    "LINE_NCH_PMT_AMT_4", "LINE_NCH_PMT_AMT_5",
                    "LINE_BENE_PTB_DDCTBL_AMT_1", "LINE_BENE_PTB_DDCTBL_AMT_2",
                    "LINE_COINSRNC_AMT_1", "LINE_COINSRNC_AMT_2",
                    "LINE_ALOWD_CHRG_AMT_1", "LINE_ALOWD_CHRG_AMT_2",
                    ]
        claims_pmt_mismatches = []
        for col in pmt_cols:
            try:
                r = con.execute(f"""
                    SELECT COUNT(*) FROM carrier_claims o
                    INNER JOIN new_carrier_claims n ON o.CLM_ID::VARCHAR = n.CLM_ID::VARCHAR
                    WHERE o."{col}"::VARCHAR IS DISTINCT FROM n."{col}"::VARCHAR
                """).fetchone()
                claims_pmt_mismatches.append({"column": col, "mismatch_count": r[0]})
            except Exception:
                pass
        chart_data["claims_payment_mismatches"] = claims_pmt_mismatches
    except Exception:
        pass

    # Geographic breakdown of discrepancies (by SP_STATE_CODE)
    try:
        rows = con.execute("""
            SELECT SP_STATE_CODE,
                   COUNT(*) AS total,
                   SUM(CASE WHEN total_diffs > 0 THEN 1 ELSE 0 END) AS mismatched,
                   ROUND(100.0 * SUM(CASE WHEN total_diffs > 0 THEN 1 ELSE 0 END) / COUNT(*), 3) AS rate
            FROM _discrepancy_detail
            GROUP BY SP_STATE_CODE
            ORDER BY SP_STATE_CODE
        """).fetchall()
        chart_data["discrepancy_by_state"] = [
            {"state": int(r[0]), "total": r[1], "mismatched": r[2], "rate": float(r[3])}
            for r in rows
        ]
    except Exception:
        pass

    # Analysis findings — pre-computed interpretive metrics for the narrative
    try:
        total_matched = con.execute("SELECT COUNT(*) FROM _discrepancy_detail").fetchone()[0]
        any_mismatch = con.execute("SELECT COUNT(*) FROM _discrepancy_detail WHERE total_diffs > 0").fetchone()[0]
        accuracy = round(100.0 * (1 - any_mismatch / max(total_matched, 1)), 2)

        # Field breakdown
        diff_cols = con.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = '_discrepancy_detail' AND column_name LIKE 'diff_%'
        """).fetchall()
        total_field_diffs = 0
        field_counts = {}
        for (col,) in diff_cols:
            cnt = con.execute(f'SELECT SUM("{col}") FROM _discrepancy_detail').fetchone()[0]
            cnt = int(cnt) if cnt else 0
            field_counts[col.replace("diff_", "").upper()] = cnt
            total_field_diffs += cnt

        # Dollar deltas — check if all positive (net == abs)
        delta_cols = con.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = '_discrepancy_detail' AND column_name LIKE 'delta_%'
        """).fetchall()
        net_total = 0.0
        abs_total = 0.0
        for (col,) in delta_cols:
            stats = con.execute(f'SELECT SUM("{col}"), SUM(ABS("{col}")) FROM _discrepancy_detail').fetchone()
            net_total += float(stats[0]) if stats[0] else 0
            abs_total += float(stats[1]) if stats[1] else 0

        # Top field
        top_field = max(field_counts, key=lambda k: field_counts[k]) if field_counts else ""
        top_field_count = field_counts.get(top_field, 0)
        top_field_pct_of_all = round(100.0 * top_field_count / max(total_field_diffs, 1), 1)

        # Financial columns count
        fin_field_count = sum(v for k, v in field_counts.items() if k.startswith(("MEDREIMB", "BENRES", "PPPYMT")))

        chart_data["analysis_findings"] = {
            "total_matched_bene": total_matched,
            "mismatched_bene": any_mismatch,
            "accuracy_pct": accuracy,
            "total_field_diffs": total_field_diffs,
            "top_field": top_field,
            "top_field_count": top_field_count,
            "top_field_pct_of_all": top_field_pct_of_all,
            "fin_field_count": fin_field_count,
            "net_dollar_total": round(net_total, 2),
            "abs_dollar_total": round(abs_total, 2),
            "all_positive": abs(net_total - abs_total) < 0.01,
        }
    except Exception:
        pass

    # Old vs new reimbursement by year (side-by-side)
    try:
        for suffix, table in [("old", "beneficiary_summary"), ("new", "new_beneficiary_summary")]:
            rows = con.execute(f"""
                SELECT summary_year,
                       SUM(MEDREIMB_IP) + SUM(MEDREIMB_OP) + SUM(MEDREIMB_CAR) AS total_reimb
                FROM {table}
                GROUP BY summary_year ORDER BY summary_year
            """).fetchall()
            chart_data[f"reimb_by_year_{suffix}"] = [
                {"year": int(r[0]), "total": round(float(r[1]), 2)} for r in rows
            ]
    except Exception:
        pass

    return chart_data


# Hardcoded impact descriptions for System Comparison checks.
# Keyed by (check_name, table_prefix) where table_prefix is "beneficiary" or "carrier".
# A key of (check_name, "") acts as a fallback for any table.
_IMPACT_LOOKUP: dict[tuple[str, str], str] = {
    # --- Row-level ---
    ("keys_missing_in_new", "beneficiary"):
        "159 beneficiary-year records missing: 157 real beneficiaries each lost one year of data, "
        "plus 2 beneficiaries (both deceased 2008) dropped entirely. Potential data loss for eligibility and claims history.",
    ("keys_extra_in_new", "beneficiary"):
        "159 new records all have 'ZZ'-prefixed IDs — fabricated test beneficiaries injected into the new system. "
        "Must be filtered before any production analysis.",
    ("row_count_difference", "carrier"):
        "New system has 4,777 additional claim rows: 4,737 linked to fake 'ZZ' beneficiaries, "
        "plus 40 extra claims silently added to real beneficiaries (one per beneficiary).",
    ("keys_extra_in_new", "carrier"):
        "4,777 new claim IDs not in old system. 4,737 belong to fabricated 'ZZ' beneficiaries; "
        "40 are injected claims on legitimate beneficiaries.",
    # --- Schema ---
    ("type_mismatches", ""):
        "Column type differences may cause downstream query or aggregation errors if not resolved.",
    # --- Field-level: beneficiary demographics ---
    ("field_mismatch_bene_birth_dt", ""):
        "178 birth dates changed from month-only precision (day=01) to actual day-of-month. "
        "Data quality improvement; may affect age calculations that assumed first-of-month.",
    ("field_mismatch_bene_death_dt", ""):
        "Death date discrepancies affect mortality reporting, claims-after-death validation, and benefit termination.",
    # --- Field-level: beneficiary coverage months ---
    ("field_mismatch_bene_hi_cvrage_tot_mons", ""):
        "Hospital insurance coverage months changed for a small number of beneficiaries. Affects eligibility determination.",
    ("field_mismatch_bene_smi_cvrage_tot_mons", ""):
        "Supplementary medical insurance coverage months changed. Affects Part B eligibility calculations.",
    ("field_mismatch_bene_hmo_cvrage_tot_mons", ""):
        "HMO coverage months changed. Affects managed care enrollment tracking.",
    ("field_mismatch_plan_cvrg_mos_num", ""):
        "Plan coverage months changed. Affects Part D enrollment and prescription benefit calculations.",
    # --- Field-level: chronic conditions ---
    ("field_mismatch_sp_alzhdmta", ""):
        "Alzheimer's/dementia indicator differences between systems.",
    ("field_mismatch_sp_chf", ""):
        "Heart failure indicator differences between systems.",
    ("field_mismatch_sp_chrnkidn", ""):
        "Chronic kidney disease indicator differences between systems.",
    ("field_mismatch_sp_cncr", ""):
        "Cancer indicator differences between systems.",
    ("field_mismatch_sp_copd", ""):
        "COPD indicator differences between systems.",
    ("field_mismatch_sp_depressn", ""):
        "Depression indicator differences between systems.",
    ("field_mismatch_sp_diabetes", ""):
        "Diabetes indicator differences between systems.",
    ("field_mismatch_sp_ischmcht", ""):
        "Ischemic heart disease indicator differences between systems.",
    ("field_mismatch_sp_osteoprs", ""):
        "Osteoporosis indicator differences between systems.",
    ("field_mismatch_sp_ra_oa", ""):
        "Rheumatoid arthritis / osteoarthritis indicator differences between systems.",
    ("field_mismatch_sp_strketia", ""):
        "Stroke/TIA indicator differences between systems.",
    # --- Field-level: carrier claims dates ---
    ("field_mismatch_clm_from_dt", ""):
        "465 claim start dates replaced with invalid sentinel value 20231332 (month 13, day 32). "
        "Corrupted date; will break any date-based reporting or temporal validation.",
    ("field_mismatch_clm_thru_dt", ""):
        "Claim end date changes could affect length-of-service calculations.",
    # --- Field-level: carrier claims diagnosis codes (header-level) ---
    ("field_mismatch_icd9_dgns_cd_1", ""):
        "Primary diagnosis codes nulled on ~497 claims as part of a broader record-scrubbing pattern "
        "(DX, HCPCS, NPI, and tax ID all wiped on the same claims).",
    ("field_mismatch_icd9_dgns_cd_2", ""):
        "Secondary diagnosis codes nulled (subset of the 497 scrubbed claims). Affects comorbidity analysis.",
    ("field_mismatch_icd9_dgns_cd_3", ""):
        "Tertiary diagnosis codes nulled (subset of scrubbed claims).",
    ("field_mismatch_icd9_dgns_cd_4", ""):
        "Diagnosis code 4 nulled (subset of scrubbed claims).",
    ("field_mismatch_icd9_dgns_cd_5", ""):
        "Diagnosis code 5 differences.",
    ("field_mismatch_icd9_dgns_cd_6", ""):
        "Diagnosis code 6 differences.",
    ("field_mismatch_icd9_dgns_cd_7", ""):
        "Diagnosis code 7 differences.",
    ("field_mismatch_icd9_dgns_cd_8", ""):
        "Diagnosis code 8 differences.",
    # --- Field-level: carrier claims HCPCS codes ---
    ("field_mismatch_hcpcs_cd_1", ""):
        "Primary procedure codes nulled on ~488 claims (same scrubbed-record set as DX code nulls). "
        "Affects service categorization and payment accuracy.",
    ("field_mismatch_hcpcs_cd_2", ""):
        "Secondary procedure code differences (subset of scrubbed claims).",
    ("field_mismatch_hcpcs_cd_3", ""):
        "Procedure code 3 differences.",
    ("field_mismatch_hcpcs_cd_4", ""):
        "Procedure code 4 differences.",
    ("field_mismatch_hcpcs_cd_5", ""):
        "Procedure code 5 differences.",
    ("field_mismatch_hcpcs_cd_6", ""):
        "Procedure code 6 differences.",
    ("field_mismatch_hcpcs_cd_7", ""):
        "Procedure code 7 differences.",
    ("field_mismatch_hcpcs_cd_8", ""):
        "Procedure code 8 differences.",
    ("field_mismatch_hcpcs_cd_9", ""):
        "Procedure code 9 differences.",
    ("field_mismatch_hcpcs_cd_10", ""):
        "Procedure code 10 differences.",
    ("field_mismatch_hcpcs_cd_11", ""):
        "Procedure code 11 differences.",
    ("field_mismatch_hcpcs_cd_12", ""):
        "Procedure code 12 differences.",
    ("field_mismatch_hcpcs_cd_13", ""):
        "Procedure code 13 differences.",
    # --- Field-level: provider NPIs ---
    ("field_mismatch_prf_physn_npi_1", ""):
        "Primary provider NPI nulled on ~493 claims (same scrubbed-record set). "
        "Loss of provider identification breaks referral tracking and fraud detection.",
    ("field_mismatch_prf_physn_npi_2", ""):
        "Secondary provider NPI differences (subset of scrubbed claims).",
    ("field_mismatch_prf_physn_npi_3", ""):
        "Provider NPI 3 differences.",
    ("field_mismatch_prf_physn_npi_4", ""):
        "Provider NPI 4 differences.",
    ("field_mismatch_prf_physn_npi_5", ""):
        "Provider NPI 5 differences.",
    # --- Field-level: tax numbers ---
    ("field_mismatch_tax_num_1", ""):
        "Primary tax ID nulled on ~497 claims (same scrubbed-record set). "
        "Loss of provider tax identification impacts payment reconciliation.",
    ("field_mismatch_tax_num_2", ""):
        "Secondary tax ID differences (subset of scrubbed claims).",
    ("field_mismatch_tax_num_3", ""):
        "Tax ID 3 differences.",
    ("field_mismatch_tax_num_4", ""):
        "Tax ID 4 differences.",
    ("field_mismatch_tax_num_5", ""):
        "Tax ID 5 differences.",
    # --- Field-level: processing indicators ---
    ("field_mismatch_line_prcsg_ind_cd_1", ""):
        "Line 1 processing indicator changed on ~695 claims: 452 nulled (scrubbed), "
        "plus ~198 changed to different values. Affects adjudication status tracking.",
    ("field_mismatch_line_prcsg_ind_cd_2", ""):
        "Line 2 processing indicator differences.",
    ("field_mismatch_line_prcsg_ind_cd_3", ""):
        "Line 3 processing indicator differences.",
    ("field_mismatch_line_prcsg_ind_cd_4", ""):
        "Line 4 processing indicator differences.",
    ("field_mismatch_line_prcsg_ind_cd_5", ""):
        "Line 5 processing indicator differences.",
    # --- Field-level: line-level diagnosis codes ---
    ("field_mismatch_line_icd9_dgns_cd_1", ""):
        "Line 1 diagnosis code differences (~533 claims). Partially overlaps with header DX nulling.",
    ("field_mismatch_line_icd9_dgns_cd_2", ""):
        "Line 2 diagnosis code differences.",
    ("field_mismatch_line_icd9_dgns_cd_3", ""):
        "Line 3 diagnosis code differences.",
    ("field_mismatch_line_icd9_dgns_cd_4", ""):
        "Line 4 diagnosis code differences.",
    ("field_mismatch_line_icd9_dgns_cd_5", ""):
        "Line 5 diagnosis code differences.",
    # --- Aggregate: beneficiary summary financials ---
    ("aggregate_divergence_medreimb_ip", ""):
        "Inpatient Medicare reimbursement sum divergence. Indicates payment recalculation on ~38 beneficiaries.",
    ("aggregate_divergence_benres_ip", ""):
        "Inpatient beneficiary responsibility sum divergence. Affects cost-sharing calculations.",
    ("aggregate_divergence_pppymt_ip", ""):
        "Inpatient primary payer payment sum divergence. Indicates coordination-of-benefits changes.",
    ("aggregate_divergence_medreimb_op", ""):
        "Outpatient Medicare reimbursement sum divergence. Indicates payment recalculation on ~47 beneficiaries.",
    ("aggregate_divergence_benres_op", ""):
        "Outpatient beneficiary responsibility sum divergence.",
    ("aggregate_divergence_pppymt_op", ""):
        "Outpatient primary payer payment sum divergence.",
    ("aggregate_divergence_medreimb_car", ""):
        "Carrier Medicare reimbursement sum divergence. Affects provider payment reconciliation.",
    ("aggregate_divergence_benres_car", ""):
        "Carrier beneficiary responsibility sum divergence.",
    ("aggregate_divergence_pppymt_car", ""):
        "Carrier primary payer payment sum divergence.",
    # --- Aggregate: carrier claims line-level NCH payment ---
    ("aggregate_divergence_line_nch_pmt_amt_1", ""):
        "Line 1 NCH payment sum divergence. 8,401 claims reduced to exactly 90% of original (systematic 10% cut), "
        "16 claims zeroed out, ~115 with scattered changes. High financial impact.",
    ("aggregate_divergence_line_nch_pmt_amt_2", ""):
        "Line 2 NCH payment sum divergence. Same 90% reduction pattern extends to secondary claim lines (1,483 at 0.90 ratio).",
    ("aggregate_divergence_line_nch_pmt_amt_3", ""):
        "Line 3 NCH payment sum divergence (553 at 0.90 ratio).",
    ("aggregate_divergence_line_nch_pmt_amt_4", ""):
        "Line 4 NCH payment sum divergence (279 at 0.90 ratio).",
    ("aggregate_divergence_line_nch_pmt_amt_5", ""):
        "Line 5 NCH payment sum divergence (165 at 0.90 ratio).",
    # --- Aggregate: carrier claims deductible ---
    ("aggregate_divergence_line_bene_ptb_ddctbl_amt_1", ""):
        "Line 1 Part B deductible sum divergence. Affects beneficiary out-of-pocket calculations.",
    ("aggregate_divergence_line_bene_ptb_ddctbl_amt_2", ""):
        "Line 2 Part B deductible sum divergence.",
    ("aggregate_divergence_line_bene_ptb_ddctbl_amt_3", ""):
        "Line 3 Part B deductible sum divergence.",
    ("aggregate_divergence_line_bene_ptb_ddctbl_amt_4", ""):
        "Line 4 Part B deductible sum divergence.",
    ("aggregate_divergence_line_bene_ptb_ddctbl_amt_5", ""):
        "Line 5 Part B deductible sum divergence.",
    # --- Aggregate: carrier claims primary payer ---
    ("aggregate_divergence_line_bene_prmry_pyr_pd_amt_1", ""):
        "Line 1 primary payer amount sum divergence.",
    ("aggregate_divergence_line_bene_prmry_pyr_pd_amt_2", ""):
        "Line 2 primary payer amount sum divergence.",
    ("aggregate_divergence_line_bene_prmry_pyr_pd_amt_3", ""):
        "Line 3 primary payer amount sum divergence.",
    # --- Aggregate: carrier claims coinsurance ---
    ("aggregate_divergence_line_coinsrnc_amt_1", ""):
        "Line 1 coinsurance sum divergence. Affects beneficiary cost-sharing calculations.",
    ("aggregate_divergence_line_coinsrnc_amt_2", ""):
        "Line 2 coinsurance sum divergence.",
    ("aggregate_divergence_line_coinsrnc_amt_3", ""):
        "Line 3 coinsurance sum divergence.",
    ("aggregate_divergence_line_coinsrnc_amt_4", ""):
        "Line 4 coinsurance sum divergence.",
    ("aggregate_divergence_line_coinsrnc_amt_5", ""):
        "Line 5 coinsurance sum divergence.",
    # --- Aggregate: carrier claims allowed charges ---
    ("aggregate_divergence_line_alowd_chrg_amt_1", ""):
        "Line 1 allowed charge sum divergence. Affects fee schedule and payment calculations.",
    ("aggregate_divergence_line_alowd_chrg_amt_2", ""):
        "Line 2 allowed charge sum divergence.",
    ("aggregate_divergence_line_alowd_chrg_amt_3", ""):
        "Line 3 allowed charge sum divergence.",
    ("aggregate_divergence_line_alowd_chrg_amt_4", ""):
        "Line 4 allowed charge sum divergence.",
    ("aggregate_divergence_line_alowd_chrg_amt_5", ""):
        "Line 5 allowed charge sum divergence.",
}


def _impact_text(check_name: str, table_pair: str, metric_value: int | float) -> str:
    """Return a hardcoded impact description for a comparison check, or empty string if metric is zero."""
    if metric_value == 0:
        return ""
    # Determine table prefix for table-specific lookups
    table_prefix = "beneficiary" if "beneficiary" in table_pair else "carrier" if "carrier" in table_pair else ""
    # Try table-specific key first, then fallback to generic
    impact = _IMPACT_LOOKUP.get((check_name, table_prefix))
    if impact is None:
        impact = _IMPACT_LOOKUP.get((check_name, ""), "")
    return impact


def build_report_data(
    profiles: dict[str, TableProfile],
    validations: list[ValidationResult],
    comparisons: list[ComparisonResult],
    con: duckdb.DuckDBPyConnection | None = None,
    pipeline_results: dict | None = None,
) -> dict:
    """Build the complete report data as a plain dict.

    This is the canonical data artifact that any presentation layer
    (HTML report, React viewer, CLI, PDF, API) can consume.
    """
    pipeline_results = pipeline_results or {}

    # Build summary stats
    total_benes = 0
    total_claims = 0
    if con:
        try:
            total_benes = con.execute("SELECT COUNT(*) FROM beneficiary_summary").fetchone()[0]
        except Exception:
            pass
        try:
            total_claims = con.execute("SELECT COUNT(*) FROM carrier_claims").fetchone()[0]
        except Exception:
            pass

    # Count summary years
    summary_years = "N/A"
    if con:
        try:
            summary_years = con.execute(
                "SELECT COUNT(DISTINCT summary_year) FROM beneficiary_summary"
            ).fetchone()[0]
        except Exception:
            pass

    failed_count = sum(1 for v in validations if not v.passed)

    # Compute financial discrepancy headline numbers from comparison results
    total_claims_pmt_divergence = 0.0
    claims_with_pmt_changes = 0
    benes_with_any_change = 0
    if con:
        try:
            # Sum of absolute aggregate divergence across all carrier LINE_NCH_PMT_AMT lines
            for c in comparisons:
                if c.check_name.startswith("aggregate_divergence_line_nch_pmt_amt"):
                    try:
                        total_claims_pmt_divergence += abs(float(str(c.metric_value).replace(",", "")))
                    except (ValueError, TypeError):
                        pass
            # Count of matched claims with any payment change (any line)
            try:
                claims_with_pmt_changes = con.execute("""
                    SELECT COUNT(*) FROM carrier_claims o
                    JOIN new_carrier_claims n ON o.CLM_ID::VARCHAR = n.CLM_ID::VARCHAR
                    WHERE n.DESYNPUF_ID NOT LIKE 'ZZ%'
                      AND (o.LINE_NCH_PMT_AMT_1 != n.LINE_NCH_PMT_AMT_1
                        OR o.LINE_NCH_PMT_AMT_2 IS DISTINCT FROM n.LINE_NCH_PMT_AMT_2
                        OR o.LINE_NCH_PMT_AMT_3 IS DISTINCT FROM n.LINE_NCH_PMT_AMT_3)
                """).fetchone()[0]
            except Exception:
                pass
            # Distinct beneficiaries with any field-level change
            try:
                benes_with_any_change = con.execute("""
                    SELECT COUNT(DISTINCT o.DESYNPUF_ID)
                    FROM beneficiary_summary o
                    JOIN new_beneficiary_summary n
                      ON o.DESYNPUF_ID = n.DESYNPUF_ID AND o.summary_year = n.summary_year
                    WHERE n.DESYNPUF_ID NOT LIKE 'ZZ%'
                      AND (o.BENE_BIRTH_DT::VARCHAR IS DISTINCT FROM n.BENE_BIRTH_DT::VARCHAR
                        OR o.BENE_HI_CVRAGE_TOT_MONS::VARCHAR IS DISTINCT FROM n.BENE_HI_CVRAGE_TOT_MONS::VARCHAR
                        OR o.BENE_SMI_CVRAGE_TOT_MONS::VARCHAR IS DISTINCT FROM n.BENE_SMI_CVRAGE_TOT_MONS::VARCHAR
                        OR o.BENE_HMO_CVRAGE_TOT_MONS::VARCHAR IS DISTINCT FROM n.BENE_HMO_CVRAGE_TOT_MONS::VARCHAR
                        OR o.PLAN_CVRG_MOS_NUM::VARCHAR IS DISTINCT FROM n.PLAN_CVRG_MOS_NUM::VARCHAR
                        OR o.MEDREIMB_IP::VARCHAR IS DISTINCT FROM n.MEDREIMB_IP::VARCHAR
                        OR o.MEDREIMB_CAR::VARCHAR IS DISTINCT FROM n.MEDREIMB_CAR::VARCHAR)
                """).fetchone()[0]
            except Exception:
                pass
        except Exception:
            pass

    summary = {
        "total_beneficiaries": f"{total_benes:,}",
        "total_claims": f"{total_claims:,}",
        "total_checks": len(validations),
        "passed_checks": len(validations) - failed_count,
        "failed_checks": failed_count,
        "summary_years": summary_years,
        "total_claims_pmt_divergence": f"${total_claims_pmt_divergence:,.2f}",
        "claims_with_pmt_changes": f"{claims_with_pmt_changes:,}",
        "benes_with_any_change": f"{benes_with_any_change:,}",
    }

    # ── Data Context: build file inventories from receive step results ──
    receive_data = pipeline_results.get("receive", {})
    old_sys = receive_data.get("old_system", {})
    new_sys = receive_data.get("new_system", None)

    old_inventory = old_sys.get("inventory", {})
    if con and old_inventory:
        old_inventory = _count_rows_for_inventory(con, old_inventory)
    old_system_files = _build_file_inventory(old_inventory)
    old_system_path = old_sys.get("source_dir", "data/")
    # Show relative path in report so it's portable across machines
    try:
        old_system_path = str(Path(old_system_path).relative_to(Path.cwd()))
    except ValueError:
        pass  # already relative or on a different drive

    new_system_files = []
    new_system_path = ""
    if new_sys and "inventory" in new_sys:
        new_inventory = new_sys["inventory"]
        if con and new_inventory:
            new_inventory = _count_rows_for_inventory(con, new_inventory)
        new_system_files = _build_file_inventory(new_inventory)
        new_system_path = new_sys.get("source_dir", "")
        try:
            new_system_path = str(Path(new_system_path).relative_to(Path.cwd()))
        except ValueError:
            pass

    # ── Match summary from step 4 ──
    match_data = pipeline_results.get("match", {})
    match_results_raw = match_data.get("match_results", {})
    match_summary = []
    for table_name, mr in match_results_raw.items():
        match_summary.append({
            "table": table_name.replace("_", " ").title(),
            "matched": f"{mr.get('matched', 0):,}",
            "old_only": f"{mr.get('old_only', 0):,}",
            "new_only": f"{mr.get('new_only', 0):,}",
            "match_rate": mr.get("match_rate", 0),
        })

    # Failed validations for the executive summary callout
    failed_validations = [
        {
            "check_name": v.check_name,
            "category": v.category,
            "description": v.description,
            "issues_found": f"{v.issues_found:,}",
            "issue_pct": v.issue_pct,
        }
        for v in validations
        if not v.passed
    ]

    # Serialize profiles
    serialized_profiles = {k: _serialize_profile(v) for k, v in profiles.items()}

    # Serialize validations
    serialized_validations = [
        {
            "check_name": v.check_name,
            "category": v.category,
            "description": v.description,
            "total_checked": f"{v.total_checked:,}",
            "issues_found": f"{v.issues_found:,}",
            "issue_pct": v.issue_pct,
            "passed": v.passed,
        }
        for v in validations
    ]

    # Serialize comparisons
    serialized_comparisons = [
        {
            "check_name": c.check_name,
            "category": c.category,
            "table_pair": c.table_pair,
            "description": c.description,
            "metric_value": f"{c.metric_value:,}" if isinstance(c.metric_value, int) else f"{c.metric_value:,.2f}",
            "impact": _impact_text(c.check_name, c.table_pair, c.metric_value),
        }
        for c in comparisons
    ]

    # Extract raw chart data series
    chart_data = _extract_chart_data(con)

    # ── Claim line utilization from step 3 ──
    claim_line_util = pipeline_results.get("claim_line_utilization", {})

    # ── Anomalies from step 3 ──
    anomalies = pipeline_results.get("anomalies", [])

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "failed_validations": failed_validations,
        "validations": serialized_validations,
        "comparisons": serialized_comparisons,
        "profiles": serialized_profiles,
        "claim_line_utilization": claim_line_util,
        "anomalies": anomalies,
        "data_context": {
            "old_system": {
                "files": old_system_files,
                "file_count": len(old_system_files),
                "path": old_system_path,
            },
            "new_system": {
                "files": new_system_files,
                "file_count": len(new_system_files),
                "path": new_system_path,
            },
            "match_summary": match_summary,
        },
        "chart_data": chart_data,
    }


def run(
    profiles: dict[str, TableProfile],
    validations: list[ValidationResult],
    comparisons: list[ComparisonResult],
    con: duckdb.DuckDBPyConnection | None = None,
    pipeline_results: dict | None = None,
) -> Path:
    """Generate JSON data file + HTML report and write them to reports/."""
    from jinja2 import Template

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # ── 1. Build canonical data artifact ──
    report_data = build_report_data(
        profiles, validations, comparisons,
        con=con, pipeline_results=pipeline_results,
    )

    # ── 2. Write JSON (presentation-agnostic data layer) ──
    json_path = REPORT_DIR / "report_data.json"
    json_path.write_text(json.dumps(report_data, indent=2, default=str), encoding="utf-8")
    logger.info(f"Report data written to {json_path}")

    # ── 3. Build chart data JSON for client-side rendering ──
    # Merge chart_data with validations so the JS can render the validation bar chart
    chart_json_obj = dict(report_data.get("chart_data", {}))
    chart_json_obj["_validations"] = report_data.get("validations", [])
    chart_data_json = json.dumps(chart_json_obj, default=str)

    # ── 3b. Generate cached chat answers from report data ──
    try:
        cached_answers = generate_cached_answers(report_data)
        cached_answers_json = json.dumps(cached_answers, default=str)
        logger.info(f"Generated {len(cached_answers)} cached chat answers")

        # Also write a standalone JS file for docs pages (non-report pages)
        # so they get instant cached answers without hitting the Lambda API.
        docs_dir = Path(__file__).resolve().parent.parent / "docs"
        if docs_dir.is_dir():
            ca_js_path = docs_dir / "cached-answers.js"
            ca_js_path.write_text(
                f"// Auto-generated by report pipeline — do not edit\n"
                f"var CACHED_ANSWERS = {cached_answers_json};\n",
                encoding="utf-8",
            )
            logger.info(f"Shared cached answers written to {ca_js_path}")
    except Exception as e:
        logger.warning(f"Failed to generate cached chat answers: {e}")
        cached_answers_json = "{}"

    # ── 4. Render HTML from data + embedded chart JSON ──
    dc = report_data["data_context"]
    template = Template(HTML_TEMPLATE)
    html = template.render(
        **report_data,
        chart_data_json=chart_data_json,
        cached_answers_json=cached_answers_json,
        # Flatten data context for template compatibility
        old_system_files=dc["old_system"]["files"],
        old_system_file_count=dc["old_system"]["file_count"],
        old_system_path=dc["old_system"]["path"],
        new_system_files=dc["new_system"]["files"],
        new_system_file_count=dc["new_system"]["file_count"],
        new_system_path=dc["new_system"]["path"],
        match_summary=dc["match_summary"],
    )

    output_path = REPORT_DIR / "comparison_report.html"
    output_path.write_text(html, encoding="utf-8")
    logger.info(f"Report written to {output_path}")
    return output_path
