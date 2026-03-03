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

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).resolve().parent.parent / "reports"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CMS Claims Comparison Report</title>
<style>
  :root {
    --bg: #0f172a; --surface: #1e293b; --border: #334155;
    --text: #e2e8f0; --muted: #94a3b8; --accent: #38bdf8;
    --green: #4ade80; --red: #f87171; --yellow: #fbbf24;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }
  .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
  h1 { font-size: 1.75rem; margin-bottom: 0.25rem; color: var(--accent); }
  h2 { font-size: 1.25rem; margin: 2rem 0 1rem; padding-bottom: 0.5rem; border-bottom: 1px solid var(--border); }
  h3 { font-size: 1rem; margin: 1.5rem 0 0.5rem; color: var(--muted); }
  .subtitle { color: var(--muted); margin-bottom: 0.25rem; font-size: 0.85rem; }
  .report-desc { color: var(--muted); margin-bottom: 2rem; font-size: 0.9rem; line-height: 1.5; max-width: 800px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; margin: 1rem 0; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin: 1rem 0; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1.25rem; }
  .card-label { font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
  .card-value { font-size: 1.5rem; font-weight: 700; margin-top: 0.25rem; }
  .card-sub { font-size: 0.8rem; color: var(--muted); margin-top: 0.25rem; }
  .card-accent { border-left: 3px solid var(--accent); }
  .card-green { border-left: 3px solid var(--green); }
  .card-red { border-left: 3px solid var(--red); }
  .card-yellow { border-left: 3px solid var(--yellow); }
  .pass { color: var(--green); }
  .fail { color: var(--red); }
  .warn { color: var(--yellow); }
  table { width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.875rem; }
  th, td { padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 600; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; cursor: pointer; user-select: none; position: relative; }
  th:hover { color: var(--accent); }
  th .sort-arrow { margin-left: 4px; font-size: 0.65rem; opacity: 0.4; }
  th.sort-asc .sort-arrow::after { content: '\\25B2'; opacity: 1; }
  th.sort-desc .sort-arrow::after { content: '\\25BC'; opacity: 1; }
  th:not(.sort-asc):not(.sort-desc) .sort-arrow::after { content: '\\25B4\\25BE'; }
  tr:hover td { background: rgba(56, 189, 248, 0.05); }
  .badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
  .badge-pass { background: rgba(74, 222, 128, 0.15); color: var(--green); }
  .badge-fail { background: rgba(248, 113, 113, 0.15); color: var(--red); }
  .badge-warn { background: rgba(251, 191, 36, 0.15); color: var(--yellow); }
  .badge-info { background: rgba(56, 189, 248, 0.15); color: var(--accent); }
  .chart-container { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; margin: 1rem 0; }
  .section { margin-bottom: 2.5rem; }
  .null-bar { display: inline-block; height: 8px; border-radius: 4px; background: var(--accent); }

  /* Collapsible sections */
  details { margin: 0.75rem 0; }
  details > summary {
    cursor: pointer; padding: 0.75rem 1rem; background: var(--surface);
    border: 1px solid var(--border); border-radius: 8px;
    font-weight: 600; font-size: 0.95rem; color: var(--text);
    list-style: none; display: flex; align-items: center; gap: 0.5rem;
    transition: background 0.15s;
  }
  details > summary:hover { background: #263348; }
  details > summary::-webkit-details-marker { display: none; }
  details > summary::before {
    content: '\\25B6'; font-size: 0.65rem; color: var(--muted);
    transition: transform 0.2s;
  }
  details[open] > summary::before { transform: rotate(90deg); }
  details[open] > summary { border-radius: 8px 8px 0 0; border-bottom-color: transparent; }
  details > .details-content {
    border: 1px solid var(--border); border-top: none;
    border-radius: 0 0 8px 8px; padding: 1rem; background: var(--surface);
  }
  .summary-meta { margin-left: auto; font-size: 0.8rem; color: var(--muted); font-weight: 400; }

  /* Nav anchors */
  .nav { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 2rem; }
  .nav a {
    padding: 0.35rem 0.75rem; border-radius: 6px; font-size: 0.8rem;
    background: var(--surface); border: 1px solid var(--border);
    color: var(--muted); text-decoration: none; transition: all 0.15s;
  }
  .nav a:hover { color: var(--accent); border-color: var(--accent); }
</style>
</head>
<body>
<div class="container">
  <h1>CMS Claims Data Comparison Report</h1>
  <p class="subtitle">Generated {{ generated_at }}</p>
  <p class="report-desc">
    Comparison of legacy CMS Medicare claims processing system outputs against a replacement system.
    This report surfaces discrepancies, quantifies their impact, and identifies trends affecting accuracy.
  </p>

  <!-- Quick Nav -->
  <div class="nav">
    <a href="#summary">Summary</a>
    <a href="#validation">Validation</a>
    <a href="#trends">Trends</a>
    <a href="#financial">Financial</a>
    <a href="#comparison">Comparison</a>
    <a href="#profiles">Data Profiles</a>
  </div>

  <!-- ============================================================ -->
  <!-- 1. EXECUTIVE SUMMARY — the most important numbers up front   -->
  <!-- ============================================================ -->
  <div class="section" id="summary">
    <h2>Executive Summary</h2>
    <div class="grid">
      <div class="card card-accent">
        <div class="card-label">Total Beneficiaries</div>
        <div class="card-value">{{ summary.total_beneficiaries }}</div>
        <div class="card-sub">Across {{ summary.summary_years }} summary years</div>
      </div>
      <div class="card card-accent">
        <div class="card-label">Total Carrier Claims</div>
        <div class="card-value">{{ summary.total_claims }}</div>
        <div class="card-sub">Parts A + B combined</div>
      </div>
      <div class="card {{ 'card-green' if summary.failed_checks == 0 else 'card-red' }}">
        <div class="card-label">Checks Passed</div>
        <div class="card-value {{ 'pass' if summary.failed_checks == 0 else '' }}">{{ summary.passed_checks }} / {{ summary.total_checks }}</div>
        <div class="card-sub">{{ summary.failed_checks }} issue{{ 's' if summary.failed_checks != 1 else '' }} detected</div>
      </div>
      <div class="card {{ 'card-green' if not comparisons else 'card-yellow' }}">
        <div class="card-label">New System Status</div>
        <div class="card-value {{ 'warn' if not comparisons else '' }}">{{ 'Loaded' if comparisons else 'Pending' }}</div>
        <div class="card-sub">{{ comparisons|length if comparisons else 'No' }} comparison checks</div>
      </div>
    </div>

    {% if failed_validations %}
    <h3 style="color: var(--red); margin-top: 1.5rem;">Issues Requiring Attention</h3>
    <div class="grid" style="grid-template-columns: 1fr;">
      {% for v in failed_validations %}
      <div class="card card-red">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <div>
            <span class="badge badge-fail">{{ v.category }}</span>
            <strong style="margin-left: 0.5rem;">{{ v.check_name }}</strong>
          </div>
          <div style="text-align: right;">
            <span class="fail" style="font-size: 1.1rem; font-weight: 700;">{{ v.issues_found }}</span>
            <span style="color: var(--muted); font-size: 0.8rem;"> issues ({{ v.issue_pct }}%)</span>
          </div>
        </div>
        <div style="color: var(--muted); margin-top: 0.35rem; font-size: 0.85rem;">{{ v.description }}</div>
      </div>
      {% endfor %}
    </div>
    {% endif %}
  </div>

  <!-- ============================================================ -->
  <!-- 2. VALIDATION RESULTS — core analysis                        -->
  <!-- ============================================================ -->
  <div class="section" id="validation">
    <h2>Validation Results</h2>
    <table>
      <thead>
        <tr><th>Check</th><th>Category</th><th>Description</th><th>Checked</th><th>Issues</th><th>Rate</th><th>Status</th></tr>
      </thead>
      <tbody>
        {% for v in validations %}
        <tr>
          <td>{{ v.check_name }}</td>
          <td><span class="badge badge-info">{{ v.category }}</span></td>
          <td>{{ v.description }}</td>
          <td>{{ v.total_checked }}</td>
          <td>{{ v.issues_found }}</td>
          <td>{{ v.issue_pct }}%</td>
          <td><span class="badge {{ 'badge-pass' if v.passed else 'badge-fail' }}">{{ 'PASS' if v.passed else 'FAIL' }}</span></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    <details>
      <summary>Issues by Check <span class="summary-meta">bar chart</span></summary>
      <div class="details-content">{{ validation_chart }}</div>
    </details>
  </div>

  <!-- ============================================================ -->
  <!-- 3. YEAR-OVER-YEAR TRENDS                                     -->
  <!-- ============================================================ -->
  {% if yoy_beneficiary_chart %}
  <div class="section" id="trends">
    <h2>Year-over-Year Trends</h2>
    <div class="grid-2">
      <div class="chart-container">{{ yoy_beneficiary_chart }}</div>
      <div class="chart-container">{{ yoy_claims_chart }}</div>
    </div>
  </div>
  {% endif %}

  <!-- ============================================================ -->
  <!-- 4. FINANCIAL ANALYSIS                                        -->
  <!-- ============================================================ -->
  {% if financial_trends_chart %}
  <div class="section" id="financial">
    <h2>Financial Analysis</h2>
    <div class="chart-container">{{ financial_trends_chart }}</div>
    <div class="grid-2">
      <div class="chart-container">{{ financial_dist_chart }}</div>
      <div class="chart-container">{{ chronic_conditions_chart }}</div>
    </div>
  </div>
  {% endif %}

  <!-- ============================================================ -->
  <!-- 5. SYSTEM COMPARISON (old vs new)                            -->
  <!-- ============================================================ -->
  <div class="section" id="comparison">
    <h2>System Comparison</h2>
    {% if comparisons %}
    <table>
      <thead>
        <tr><th>Check</th><th>Category</th><th>Table Pair</th><th>Description</th><th>Metric</th></tr>
      </thead>
      <tbody>
        {% for c in comparisons %}
        <tr>
          <td>{{ c.check_name }}</td>
          <td><span class="badge badge-info">{{ c.category }}</span></td>
          <td>{{ c.table_pair }}</td>
          <td>{{ c.description }}</td>
          <td>{{ c.metric_value }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <div class="card card-yellow">
      <div class="card-label">Awaiting New System Data</div>
      <div class="card-value warn">Not Yet Loaded</div>
      <p style="color: var(--muted); margin-top: 0.5rem; font-size: 0.875rem;">
        To run old-vs-new comparison: <code style="background: var(--bg); padding: 0.15rem 0.4rem; border-radius: 3px;">python -m src.main --new-data path/to/csvs/</code>
      </p>
      <p style="color: var(--muted); margin-top: 0.35rem; font-size: 0.85rem;">
        Expected format: CSVs with matching schemas for Beneficiary Summary and Carrier Claims files.
      </p>
    </div>
    {% endif %}
  </div>

  <!-- ============================================================ -->
  <!-- 6. DATA PROFILES — collapsible reference material            -->
  <!-- ============================================================ -->
  <div class="section" id="profiles">
    <h2>Data Profiles</h2>
    <p style="color: var(--muted); margin-bottom: 1rem; font-size: 0.85rem;">
      Column-level quality profiles for each ingested table. Click to expand.
    </p>
    {% for tname, profile in profiles.items() %}
    <details>
      <summary>
        {{ tname }}
        <span class="summary-meta">{{ profile.row_count }} rows, {{ profile.column_count }} cols{% if profile.high_null_cols %} &middot; <span class="warn">{{ profile.high_null_cols }} high-null cols</span>{% endif %}</span>
      </summary>
      <div class="details-content">
        <table>
          <thead>
            <tr><th>Column</th><th>Type</th><th>Nulls</th><th>Null %</th><th>Distinct</th><th>Min</th><th>Max</th><th>Mean</th></tr>
          </thead>
          <tbody>
            {% for col in profile.columns %}
            <tr>
              <td>{{ col.name }}</td>
              <td><span class="badge badge-info">{{ col.dtype }}</span></td>
              <td>{{ col.null_count }}</td>
              <td>
                <span class="{{ 'fail' if col.null_pct > 80 else 'warn' if col.null_pct > 50 else '' }}">{{ col.null_pct }}%</span>
                <div class="null-bar" style="width: {{ col.null_pct }}%"></div>
              </td>
              <td>{{ col.distinct_count }}</td>
              <td>{{ col.min_val or '-' }}</td>
              <td>{{ col.max_val or '-' }}</td>
              <td>{{ '%.2f'|format(col.mean_val) if col.mean_val is not none else '-' }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </details>
    {% endfor %}
  </div>

  <!-- ============================================================ -->
  <!-- Footer                                                       -->
  <!-- ============================================================ -->
  <div style="margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center;">
    <p style="color: var(--muted); font-size: 0.8rem;">
      Pipeline: INGEST &rarr; PROFILE &rarr; VALIDATE &rarr; COMPARE &rarr; REPORT
    </p>
    <p style="color: var(--muted); font-size: 0.8rem;">
      CMS DE-SynPUF 2008&ndash;2010 &middot; DuckDB + Python
    </p>
  </div>
</div>
<script>
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('table').forEach(function(table) {
    var headers = table.querySelectorAll('th');
    headers.forEach(function(th, colIdx) {
      var arrow = document.createElement('span');
      arrow.className = 'sort-arrow';
      th.appendChild(arrow);
      th.addEventListener('click', function() {
        var isAsc = th.classList.contains('sort-asc');
        headers.forEach(function(h) { h.classList.remove('sort-asc', 'sort-desc'); });
        th.classList.add(isAsc ? 'sort-desc' : 'sort-asc');
        var tbody = table.querySelector('tbody') || table;
        var rows = Array.from(tbody.querySelectorAll('tr'));
        if (tbody === table) {
          rows = rows.filter(function(r) { return !r.querySelector('th'); });
        }
        rows.sort(function(a, b) {
          var aCell = a.cells[colIdx];
          var bCell = b.cells[colIdx];
          if (!aCell || !bCell) return 0;
          var aText = aCell.textContent.trim();
          var bText = bCell.textContent.trim();
          var aNum = parseFloat(aText.replace(/[,%$]/g, ''));
          var bNum = parseFloat(bText.replace(/[,%$]/g, ''));
          if (!isNaN(aNum) && !isNaN(bNum)) {
            return isAsc ? bNum - aNum : aNum - bNum;
          }
          return isAsc ? bText.localeCompare(aText) : aText.localeCompare(bText);
        });
        rows.forEach(function(row) { (tbody === table ? table : tbody).appendChild(row); });
      });
    });
  });
});
</script>
</body>
</html>"""


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
    return pio.to_html(fig, full_html=False, include_plotlyjs="cdn")


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


def run(
    profiles: dict[str, TableProfile],
    validations: list[ValidationResult],
    comparisons: list[ComparisonResult],
    con: duckdb.DuckDBPyConnection | None = None,
) -> Path:
    """Generate the HTML report and write it to reports/."""
    from jinja2 import Template

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

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
    summary = {
        "total_beneficiaries": f"{total_benes:,}",
        "total_claims": f"{total_claims:,}",
        "total_checks": len(validations),
        "passed_checks": len(validations) - failed_count,
        "failed_checks": failed_count,
        "summary_years": summary_years,
    }

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
        }
        for c in comparisons
    ]

    # Build charts
    validation_chart = _build_validation_chart(validations) if validations else ""

    # Enhanced charts (need DB connection)
    yoy_beneficiary_chart = ""
    yoy_claims_chart = ""
    financial_trends_chart = ""
    financial_dist_chart = ""
    chronic_conditions_chart = ""
    if con:
        yoy_beneficiary_chart = _build_yoy_beneficiary_chart(con)
        yoy_claims_chart = _build_yoy_claims_chart(con)
        financial_trends_chart = _build_financial_trends_chart(con)
        financial_dist_chart = _build_financial_distribution_chart(con)
        chronic_conditions_chart = _build_chronic_conditions_chart(con)

    # Render
    template = Template(HTML_TEMPLATE)
    html = template.render(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        summary=summary,
        failed_validations=failed_validations,
        profiles=serialized_profiles,
        validations=serialized_validations,
        comparisons=serialized_comparisons,
        validation_chart=validation_chart,
        yoy_beneficiary_chart=yoy_beneficiary_chart,
        yoy_claims_chart=yoy_claims_chart,
        financial_trends_chart=financial_trends_chart,
        financial_dist_chart=financial_dist_chart,
        chronic_conditions_chart=chronic_conditions_chart,
    )

    output_path = REPORT_DIR / "comparison_report.html"
    output_path.write_text(html, encoding="utf-8")
    logger.info(f"Report written to {output_path}")
    return output_path
