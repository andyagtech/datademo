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
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
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

  /* -- Project Nav -- */
  .project-nav {
    position: fixed; top: 0; left: 0; right: 0; z-index: 300;
    height: 32px; background: #0a0c14; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; padding: 0 16px; gap: 6px;
    font-size: 0.7rem; font-family: 'Inter', system-ui, sans-serif;
  }
  .project-nav a {
    color: var(--muted); text-decoration: none; padding: 3px 8px;
    border-radius: 4px; transition: all 0.15s; white-space: nowrap;
  }
  .project-nav a:hover { color: var(--text); background: rgba(56,189,248,0.08); }
  .project-nav a.active { color: var(--accent); background: rgba(56,189,248,0.1); }
  .project-nav .nav-sep { color: var(--border); margin: 0 2px; }
  .project-nav .nav-home { font-weight: 700; color: var(--accent); }
  .project-nav .nav-home:hover { background: rgba(56,189,248,0.12); }

  /* Sidebar nav */
  .sidebar {
    position: fixed; top: 32px; left: 0; width: 220px; height: calc(100vh - 32px);
    background: var(--surface); border-right: 1px solid var(--border);
    padding: 1.25rem 0; overflow-y: auto; z-index: 100;
    display: flex; flex-direction: column;
  }
  .sidebar-title {
    font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--muted); padding: 0 1rem;
    margin-bottom: 0.75rem;
  }
  .sidebar a {
    display: block; padding: 0.45rem 1rem 0.45rem 1.15rem;
    font-size: 0.82rem; color: var(--muted); text-decoration: none;
    border-left: 3px solid transparent; transition: all 0.15s;
    line-height: 1.4;
  }
  .sidebar a:hover { color: var(--text); background: rgba(56, 189, 248, 0.05); }
  .sidebar a.active {
    color: var(--accent); border-left-color: var(--accent);
    background: rgba(56, 189, 248, 0.08); font-weight: 600;
  }
  .sidebar-divider { height: 1px; background: var(--border); margin: 0.5rem 1rem; }
  .container { margin-left: 220px; }
  @media (max-width: 900px) {
    .sidebar { display: none; }
    .container { margin-left: 0; }
  }
</style>
</head>
<body>

<nav class="project-nav">
  <a href="../index.html" class="nav-home">&#9671; Docs</a>
  <span class="nav-sep">|</span>
  <a href="comparison_report.html" class="active">Report</a>
  <a href="../architecture.html">Architecture</a>
  <a href="../schema_explorer.html">Schema</a>
  <a href="../parquet_viewer.html">Parquet</a>
  <a href="../sql_explorer.html">SQL</a>
</nav>

<div class="container" style="padding-top: calc(2rem + 32px)">
  <h1>CMS Claims Data Comparison Report</h1>
  <p class="subtitle">Generated {{ generated_at }}</p>

  <!-- Sidebar Navigation -->
  <nav class="sidebar" id="sidebar">
    <div class="sidebar-title">Report Sections</div>
    <a href="#data-context" data-section="data-context">Data Context</a>
    <a href="#summary" data-section="summary">Executive Summary</a>
    <a href="#discrepancies" data-section="discrepancies">Discrepancies</a>
    <div class="sidebar-divider"></div>
    <a href="#validation" data-section="validation">Validation</a>
    <a href="#trends" data-section="trends">YoY Trends</a>
    <a href="#financial" data-section="financial">Financial Analysis</a>
    <div class="sidebar-divider"></div>
    <a href="#comparison" data-section="comparison">System Comparison</a>
    <a href="#profiles" data-section="profiles">Data Profiles</a>
  </nav>

  <!-- ============================================================ -->
  <!-- 0. DATA CONTEXT — what exactly is being compared              -->
  <!-- ============================================================ -->
  <div class="section" id="data-context">
    <h2>Data Under Comparison</h2>
    <p style="color: var(--muted); margin-bottom: 1.25rem; font-size: 0.9rem; line-height: 1.7; max-width: 900px;">
      This report compares outputs from two CMS Medicare claims processing systems.
      The <strong style="color: var(--accent);">old system</strong> is the legacy production pipeline
      (CMS DE-SynPUF reference dataset, 2008&ndash;2010).
      The <strong style="color: #4ade80;">new system</strong> is the replacement pipeline whose outputs
      are validated against the old system to ensure correctness before cutover.
    </p>

    <div class="grid-2">
      <!-- Old System -->
      <div class="card card-accent">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
          <strong style="font-size: 1rem;">Old System (Reference)</strong>
          <span class="badge badge-info">{{ old_system_file_count }} files</span>
        </div>
        <table style="margin: 0; font-size: 0.8rem;">
          <thead><tr><th style="font-size: 0.7rem;">File</th><th style="font-size: 0.7rem;">Rows</th><th style="font-size: 0.7rem;">Size</th></tr></thead>
          <tbody>
            {% for f in old_system_files %}
            <tr><td style="font-size: 0.8rem;">{{ f.name }}</td><td>{{ f.rows }}</td><td>{{ f.size }}</td></tr>
            {% endfor %}
          </tbody>
        </table>
        <div style="margin-top: 0.75rem; font-size: 0.8rem; color: var(--muted);">
          Source: <code style="background: var(--bg); padding: 0.1rem 0.3rem; border-radius: 3px; font-size: 0.75rem;">{{ old_system_path }}</code>
        </div>
      </div>

      <!-- New System -->
      <div class="card" style="border-left: 3px solid #4ade80;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
          <strong style="font-size: 1rem;">New System (Under Test)</strong>
          {% if new_system_files %}
          <span class="badge badge-pass">{{ new_system_file_count }} files</span>
          {% else %}
          <span class="badge badge-warn">Not loaded</span>
          {% endif %}
        </div>
        {% if new_system_files %}
        <table style="margin: 0; font-size: 0.8rem;">
          <thead><tr><th style="font-size: 0.7rem;">File</th><th style="font-size: 0.7rem;">Rows</th><th style="font-size: 0.7rem;">Size</th></tr></thead>
          <tbody>
            {% for f in new_system_files %}
            <tr><td style="font-size: 0.8rem;">{{ f.name }}</td><td>{{ f.rows }}</td><td>{{ f.size }}</td></tr>
            {% endfor %}
          </tbody>
        </table>
        <div style="margin-top: 0.75rem; font-size: 0.8rem; color: var(--muted);">
          Source: <code style="background: var(--bg); padding: 0.1rem 0.3rem; border-radius: 3px; font-size: 0.75rem;">{{ new_system_path }}</code>
        </div>
        {% else %}
        <p style="color: var(--muted); font-size: 0.85rem; margin-top: 0.5rem;">New system data has not been loaded yet. Run with <code style="background: var(--bg); padding: 0.1rem 0.3rem; border-radius: 3px;">--new-data path/to/csvs/</code></p>
        {% endif %}
      </div>
    </div>

    {% if match_summary %}
    <!-- Match summary -->
    <h3 style="margin-top: 1.5rem;">Record Matching Results</h3>
    <div class="grid">
      {% for m in match_summary %}
      <div class="card {{ 'card-green' if m.match_rate >= 99.5 else 'card-yellow' if m.match_rate >= 95 else 'card-red' }}">
        <div class="card-label">{{ m.table }}</div>
        <div class="card-value {{ 'pass' if m.match_rate >= 99.5 else 'warn' if m.match_rate >= 95 else 'fail' }}">{{ m.match_rate }}%</div>
        <div class="card-sub">{{ m.matched }} matched &middot; {{ m.old_only }} old-only &middot; {{ m.new_only }} new-only</div>
      </div>
      {% endfor %}
    </div>
    {% endif %}
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
  <!-- 1b. DISCREPANCY DASHBOARD — the spec's core ask              -->
  <!-- ============================================================ -->
  <div class="section" id="discrepancies">
    <h2>Discrepancy Dashboard</h2>
    <p style="color: var(--muted); margin-bottom: 1rem; font-size: 0.88rem; line-height: 1.6; max-width: 900px;">
      The old system (CMS DE-SynPUF) is treated as <strong style="color: var(--accent);">ground truth</strong>.
      All metrics below quantify how the new system's outputs <strong style="color: var(--yellow);">deviate</strong>
      from the old system. Discrepancies indicate potential issues in the new claims processing pipeline
      that must be resolved before cutover.
    </p>

    <!-- Key discrepancy KPIs -->
    <div class="grid">
      <div class="card card-red" id="kpi-bene-mismatch">
        <div class="card-label">Beneficiaries with Data Mismatches</div>
        <div class="card-value fail" id="kpi-bene-mismatch-val">—</div>
        <div class="card-sub" id="kpi-bene-mismatch-sub"></div>
      </div>
      <div class="card card-red" id="kpi-claims-pmt">
        <div class="card-label">Claims with Payment Mismatches</div>
        <div class="card-value fail" id="kpi-claims-pmt-val">—</div>
        <div class="card-sub" id="kpi-claims-pmt-sub"></div>
      </div>
      <div class="card card-yellow" id="kpi-fin-diverge">
        <div class="card-label">Total Financial Divergence</div>
        <div class="card-value warn" id="kpi-fin-diverge-val">—</div>
        <div class="card-sub" id="kpi-fin-diverge-sub">Sum of absolute differences across all reimbursement columns</div>
      </div>
      <div class="card" style="border-left: 3px solid var(--accent);" id="kpi-phantom">
        <div class="card-label">Phantom / Missing Records</div>
        <div class="card-value" id="kpi-phantom-val">—</div>
        <div class="card-sub" id="kpi-phantom-sub">Records in one system but not the other</div>
      </div>
    </div>

    <!-- Key Findings — interpretive narrative (rendered by JS from analysis data) -->
    <div id="key-findings" style="margin-top: 1.5rem; display: none;">
      <h3 style="margin-bottom: 0.75rem;">Key Findings</h3>
      <div class="card" style="border-left: 3px solid var(--yellow); line-height: 1.8; font-size: 0.88rem;">
        <p id="finding-accuracy" style="margin-bottom: 0.6rem;"></p>
        <p id="finding-top-field" style="margin-bottom: 0.6rem;"></p>
        <p id="finding-financial" style="margin-bottom: 0.6rem;"></p>
        <p id="finding-claims" style="margin-bottom: 0.6rem;"></p>
        <p id="finding-phantom" style="margin-bottom: 0.6rem;"></p>
        <p id="finding-trend" style="margin-bottom: 0;"></p>
      </div>

      <h3 style="margin-top: 1.25rem; margin-bottom: 0.5rem;">What This Means for Accuracy</h3>
      <div class="card" style="border-left: 3px solid #4ade80; line-height: 1.8; font-size: 0.88rem;">
        <p id="meaning-accuracy" style="margin-bottom: 0.6rem;"></p>
        <p id="meaning-risk" style="margin-bottom: 0;"></p>
      </div>
    </div>

    <!-- Discrepancy charts -->
    <div class="grid-2" style="margin-top: 1.5rem;">
      <div class="chart-container">
        <div id="chart-field-mismatches" style="width:100%;height:400px;"></div>
      </div>
      <div class="chart-container">
        <div id="chart-discrepancy-trend" style="width:100%;height:400px;"></div>
      </div>
    </div>
    <div class="grid-2">
      <div class="chart-container">
        <div id="chart-fin-divergence" style="width:100%;height:400px;"></div>
      </div>
      <div class="chart-container">
        <div id="chart-reimb-comparison" style="width:100%;height:400px;"></div>
      </div>
    </div>
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
      <div class="details-content"><div id="chart-validation" style="width:100%;height:350px;"></div></div>
    </details>
  </div>

  <!-- ============================================================ -->
  <!-- 3. YEAR-OVER-YEAR TRENDS                                     -->
  <!-- ============================================================ -->
  <div class="section" id="trends">
    <h2>Year-over-Year Trends</h2>
    <div class="grid-2">
      <div class="chart-container"><div id="chart-yoy-bene" style="width:100%;height:350px;"></div></div>
      <div class="chart-container"><div id="chart-yoy-claims" style="width:100%;height:350px;"></div></div>
    </div>
  </div>

  <!-- ============================================================ -->
  <!-- 4. FINANCIAL ANALYSIS                                        -->
  <!-- ============================================================ -->
  <div class="section" id="financial">
    <h2>Financial Analysis</h2>
    <div class="chart-container"><div id="chart-financial-trends" style="width:100%;height:400px;"></div></div>
    <div class="grid-2">
      <div class="chart-container"><div id="chart-financial-dist" style="width:100%;height:400px;"></div></div>
      <div class="chart-container"><div id="chart-chronic" style="width:100%;height:400px;"></div></div>
    </div>
  </div>

  <!-- ============================================================ -->
  <!-- 5. SYSTEM COMPARISON (old vs new)                            -->
  <!-- ============================================================ -->
  <div class="section" id="comparison">
    <h2>System Comparison</h2>
    {% if comparisons %}
    <details open>
      <summary>
        All Comparison Checks
        <span class="summary-meta">{{ comparisons|length }} checks across schema, row-level, field-level, and aggregate categories</span>
      </summary>
      <div class="details-content">
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
      </div>
    </details>
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
var REPORT_DATA = {{ chart_data_json }};

document.addEventListener('DOMContentLoaded', function() {
  var dark = {plot_bgcolor:'#1e293b',paper_bgcolor:'#1e293b',font:{color:'#e2e8f0',size:11},margin:{l:60,r:30,t:50,b:40}};
  var gridColor = '#334155';

  /* ================================================================ */
  /* DISCREPANCY DASHBOARD — KPIs + Charts                           */
  /* ================================================================ */

  /* -- KPI: Beneficiaries with data mismatches -- */
  var dby = REPORT_DATA.discrepancy_by_year || [];
  if (dby.length) {
    var totalBene = dby.reduce(function(s,r){return s+r.total;},0);
    var mismatchedBene = dby.reduce(function(s,r){return s+r.mismatched;},0);
    var benePct = (100.0 * mismatchedBene / Math.max(totalBene,1)).toFixed(2);
    document.getElementById('kpi-bene-mismatch-val').textContent = mismatchedBene.toLocaleString();
    document.getElementById('kpi-bene-mismatch-sub').textContent = benePct + '% of ' + totalBene.toLocaleString() + ' matched beneficiary-years';
  }

  /* -- KPI: Claims with payment mismatches -- */
  var cpm = REPORT_DATA.claims_payment_mismatches || [];
  if (cpm.length) {
    var totalClaimsMismatch = cpm.reduce(function(s,r){return s+r.mismatch_count;},0);
    var volClaims = REPORT_DATA.volume_claims || {};
    document.getElementById('kpi-claims-pmt-val').textContent = totalClaimsMismatch.toLocaleString();
    var claimDenom = volClaims.old || 0;
    document.getElementById('kpi-claims-pmt-sub').textContent = 'Across ' + cpm.length + ' payment columns on ' + claimDenom.toLocaleString() + ' matched claims';
  }

  /* -- KPI: Total financial divergence -- */
  var finDiv = REPORT_DATA.financial_divergence || [];
  if (finDiv.length) {
    var totalAbsDiff = finDiv.reduce(function(s,r){return s+r.abs_diff;},0);
    document.getElementById('kpi-fin-diverge-val').textContent = '$' + totalAbsDiff.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
  }

  /* -- KPI: Phantom / missing records -- */
  var volB = REPORT_DATA.volume_beneficiaries || {};
  var volC = REPORT_DATA.volume_claims || {};
  if (volB.old || volC.old) {
    var bDiff = Math.abs(volB.diff || 0);
    var cDiff = Math.abs(volC.diff || 0);
    document.getElementById('kpi-phantom-val').textContent = (bDiff + cDiff).toLocaleString();
    var parts = [];
    if (volB.diff > 0) parts.push(volB.diff.toLocaleString() + ' extra beneficiaries in new');
    if (volB.diff < 0) parts.push(Math.abs(volB.diff).toLocaleString() + ' missing beneficiaries in new');
    if (volC.diff > 0) parts.push(volC.diff.toLocaleString() + ' extra claims in new');
    if (volC.diff < 0) parts.push(Math.abs(volC.diff).toLocaleString() + ' missing claims in new');
    if (parts.length) document.getElementById('kpi-phantom-sub').textContent = parts.join(' · ');
  }

  /* -- Key Findings narrative (interpretive analysis) -- */
  var af = REPORT_DATA.analysis_findings || {};
  if (af.total_matched_bene) {
    document.getElementById('key-findings').style.display = 'block';

    document.getElementById('finding-accuracy').innerHTML =
      '<strong style="color:var(--accent);">Overall accuracy: ' + af.accuracy_pct + '%.</strong> ' +
      'Of ' + af.total_matched_bene.toLocaleString() + ' matched beneficiary-year records, ' +
      af.mismatched_bene.toLocaleString() + ' (' + (100 - af.accuracy_pct).toFixed(2) + '%) have at least one field that differs between the old and new systems.';

    document.getElementById('finding-top-field').innerHTML =
      '<strong style="color:#f87171;">Primary issue: ' + af.top_field + ' mismatches.</strong> ' +
      af.top_field_count.toLocaleString() + ' records (' + af.top_field_pct_of_all + '% of all field-level discrepancies) have different ' + af.top_field + ' values. ' +
      (af.top_field === 'BENE_BIRTH_DT' ?
        'This is consistent across all three summary years, suggesting a <em>systematic date parsing or migration bug</em> in the new system rather than random data corruption.' :
        'This field accounts for the largest share of discrepancies.');

    var directionNote = af.all_positive ?
      'All dollar deltas are <em>positive</em> — the new system consistently <strong style="color:#fbbf24;">overstates</strong> reimbursements, never understates them. This one-directional pattern indicates a <em>systematic calculation bias</em>, not random noise.' :
      'Dollar deltas go in both directions, suggesting random calculation errors rather than a systematic bias.';
    document.getElementById('finding-financial').innerHTML =
      '<strong style="color:#fbbf24;">Financial divergence: $' + af.abs_dollar_total.toLocaleString(undefined,{minimumFractionDigits:2}) + '.</strong> ' +
      'Across ' + af.fin_field_count.toLocaleString() + ' financial field mismatches on 9 reimbursement columns (IP/OP/CAR × Medicare/Beneficiary/PrimaryPayer). ' +
      directionNote;

    var cpm2 = REPORT_DATA.claims_payment_mismatches || [];
    if (cpm2.length) {
      var topClaim = cpm2.reduce(function(a,b){return a.mismatch_count > b.mismatch_count ? a : b;});
      var otherCount = cpm2.reduce(function(s,r){return s + r.mismatch_count;}, 0) - topClaim.mismatch_count;
      document.getElementById('finding-claims').innerHTML =
        '<strong style="color:#f87171;">Claims payment mismatches: ' + topClaim.mismatch_count.toLocaleString() + ' on ' + topClaim.column + '.</strong> ' +
        'This is ' + Math.round(topClaim.mismatch_count / Math.max(otherCount,1)) + 'x more than all other payment columns combined (' + otherCount.toLocaleString() + '), ' +
        'indicating a targeted calculation error in the primary payment amount logic.';
    }

    if (volC.diff) {
      document.getElementById('finding-phantom').innerHTML =
        '<strong>Phantom records: ' + Math.abs(volC.diff).toLocaleString() + ' claims.</strong> ' +
        (volC.diff > 0 ?
          'The new system generates ' + volC.diff.toLocaleString() + ' claims that have no corresponding record in the old system. Zero claims are lost (old-only = 0). This suggests the new system is <em>creating spurious claim records</em>.' :
          Math.abs(volC.diff).toLocaleString() + ' claims exist in the old system but are missing from the new system (data loss).');
    }

    if (dby.length >= 2) {
      var rates = dby.map(function(r){return r.pct;});
      var minRate = Math.min.apply(null, rates);
      var maxRate = Math.max.apply(null, rates);
      var spread = maxRate - minRate;
      document.getElementById('finding-trend').innerHTML =
        '<strong>Trend stability:</strong> ' +
        (spread < 0.1 ?
          'Discrepancy rates are <strong style="color:#4ade80;">stable across years</strong> (' + minRate + '%–' + maxRate + '%), suggesting the errors are inherent to the migration logic rather than worsening over time.' :
          'Discrepancy rates vary across years (' + minRate + '%–' + maxRate + '%), suggesting the issue may be time-dependent or data-volume-dependent.');
    }

    // What this means for accuracy
    var riskLevel = af.accuracy_pct >= 99.5 ? 'low' : af.accuracy_pct >= 98 ? 'moderate' : 'high';
    document.getElementById('meaning-accuracy').innerHTML =
      'The new system achieves <strong>' + af.accuracy_pct + '% record-level accuracy</strong> on beneficiary data. ' +
      (riskLevel === 'low' ? 'This is a strong result — fewer than 1 in 200 records are affected.' :
       riskLevel === 'moderate' ? 'This needs investigation — more than 1 in 50 records are affected.' :
       'This is a significant concern — accuracy is below 98%.');

    var totalReimb = (REPORT_DATA.reimb_by_year_old || []).reduce(function(s,r){return s+r.total;},0);
    var finPct = totalReimb > 0 ? (100.0 * af.abs_dollar_total / totalReimb).toFixed(4) : '0';
    document.getElementById('meaning-risk').innerHTML =
      '<strong>Risk assessment:</strong> The $' + af.abs_dollar_total.toLocaleString(undefined,{minimumFractionDigits:2}) +
      ' financial divergence represents <strong>' + finPct + '%</strong> of $' + (totalReimb/1e9).toFixed(2) + 'B total reimbursements — ' +
      '<em>negligible in aggregate</em>. However, the concentration in specific fields (' + af.top_field + ', ' +
      (cpm2.length ? cpm2[0].column : 'payment amounts') + ') and the one-directional bias suggest <strong style="color:#fbbf24;">two distinct bugs</strong> ' +
      'that should be fixed before production cutover: (1) a date handling issue and (2) a payment calculation issue.';
  }

  /* -- Chart: Geographic distribution of discrepancies -- */
  var dbs = REPORT_DATA.discrepancy_by_state || [];
  if (dbs.length) {
    var dbsFiltered = dbs.filter(function(r){return r.mismatched > 0;}).sort(function(a,b){return b.rate - a.rate;}).slice(0,25);
    if (dbsFiltered.length && document.getElementById('chart-field-mismatches')) {
      // We'll add a small geographic note
    }
  }

  /* -- Chart: Top field mismatches (horizontal bar) -- */
  var fm = REPORT_DATA.field_mismatches || [];
  if (fm.length) {
    var fmTop = fm.slice(0, 20);
    Plotly.newPlot('chart-field-mismatches',[{
      x: fmTop.map(function(r){return r.mismatch_count;}),
      y: fmTop.map(function(r){return r.field;}),
      orientation:'h', type:'bar',
      marker:{color:fmTop.map(function(r){return r.mismatch_count > 100 ? '#f87171' : '#fbbf24';})},
      text:fmTop.map(function(r){return r.mismatch_count.toLocaleString();}),
      textposition:'outside'
    }],Object.assign({},dark,{
      title:'Top Mismatched Fields (New vs Old)',
      xaxis:{title:'Mismatched Records',gridcolor:gridColor},
      yaxis:{autorange:'reversed',gridcolor:gridColor},
      height:400,margin:{l:200,r:60,t:50,b:40}
    }),{responsive:true});
  }

  /* -- Chart: Discrepancy trend by year -- */
  if (dby.length) {
    var dbyYears = dby.map(function(r){return String(r.year);});
    Plotly.newPlot('chart-discrepancy-trend',[
      {x:dbyYears,y:dby.map(function(r){return r.total;}),name:'Total Matched',type:'bar',marker:{color:'#334155'}},
      {x:dbyYears,y:dby.map(function(r){return r.mismatched;}),name:'With Mismatches',type:'bar',marker:{color:'#f87171'}},
      {x:dbyYears,y:dby.map(function(r){return r.pct;}),name:'Mismatch %',type:'scatter',mode:'lines+markers',yaxis:'y2',line:{color:'#fbbf24',width:3},marker:{size:8}}
    ],Object.assign({},dark,{
      barmode:'overlay',
      title:'Beneficiary Discrepancy Trend by Year',
      xaxis:{title:'Year',gridcolor:gridColor},
      yaxis:{title:'Records',gridcolor:gridColor},
      yaxis2:{title:'Mismatch %',overlaying:'y',side:'right',gridcolor:'rgba(0,0,0,0)',showgrid:false,ticksuffix:'%'},
      legend:{bgcolor:'rgba(0,0,0,0)',x:0.01,y:0.99},
      height:400,margin:{l:70,r:70,t:50,b:40}
    }),{responsive:true});
  }

  /* -- Chart: Financial divergence by column -- */
  if (finDiv.length) {
    var fdCols = finDiv.map(function(r){return r.column;});
    var fdColors = finDiv.map(function(r){return r.diff > 0 ? '#4ade80' : '#f87171';});
    Plotly.newPlot('chart-fin-divergence',[{
      x:fdCols,y:finDiv.map(function(r){return r.diff;}),
      type:'bar',marker:{color:fdColors},
      text:finDiv.map(function(r){return '$'+r.diff.toLocaleString(undefined,{minimumFractionDigits:0});}),
      textposition:'outside'
    }],Object.assign({},dark,{
      title:'Financial Divergence: New − Old (by column)',
      xaxis:{title:'Reimbursement Column',gridcolor:gridColor,tickangle:-35},
      yaxis:{title:'Dollar Difference ($)',gridcolor:gridColor},
      height:400,margin:{l:80,r:30,t:50,b:100}
    }),{responsive:true});
  }

  /* -- Chart: Old vs New total reimbursement by year -- */
  var reimbOld = REPORT_DATA.reimb_by_year_old || [];
  var reimbNew = REPORT_DATA.reimb_by_year_new || [];
  if (reimbOld.length && reimbNew.length) {
    Plotly.newPlot('chart-reimb-comparison',[
      {x:reimbOld.map(function(r){return String(r.year);}),y:reimbOld.map(function(r){return r.total;}),name:'Old System (Truth)',type:'bar',marker:{color:'#38bdf8'}},
      {x:reimbNew.map(function(r){return String(r.year);}),y:reimbNew.map(function(r){return r.total;}),name:'New System',type:'bar',marker:{color:'#4ade80',opacity:0.7}}
    ],Object.assign({},dark,{
      barmode:'group',
      title:'Total Medicare Reimbursement: Old vs New',
      xaxis:{title:'Year',gridcolor:gridColor},
      yaxis:{title:'Total Reimbursement ($)',gridcolor:gridColor},
      legend:{bgcolor:'rgba(0,0,0,0)'},
      height:400,margin:{l:80,r:30,t:50,b:40}
    }),{responsive:true});
  }

  /* ================================================================ */
  /* EXISTING CHARTS                                                  */
  /* ================================================================ */

  /* -- Validation bar chart -- */
  var vals = REPORT_DATA._validations || [];
  if (vals.length) {
    var vChecks = vals.map(function(v){return v.check_name;});
    var vIssues = vals.map(function(v){return parseInt(String(v.issues_found).replace(/,/g,''))||0;});
    var vColors = vIssues.map(function(i){return i>0?'#f87171':'#4ade80';});
    Plotly.newPlot('chart-validation',[{x:vIssues,y:vChecks,orientation:'h',type:'bar',marker:{color:vColors},text:vIssues.map(function(i){return i.toLocaleString();}),textposition:'outside'}],
      Object.assign({},dark,{title:'Issues Found Per Validation Check',xaxis:{title:'Issues Found',gridcolor:gridColor},yaxis:{autorange:'reversed',gridcolor:gridColor},height:Math.max(350,vChecks.length*35),margin:{l:250,r:60,t:50,b:40}}),{responsive:true});
  }

  /* -- YoY Beneficiaries -- */
  var yoyB = REPORT_DATA.yoy_beneficiaries || [];
  if (yoyB.length) {
    Plotly.newPlot('chart-yoy-bene',[{x:yoyB.map(function(r){return String(r.year);}),y:yoyB.map(function(r){return r.count;}),type:'bar',marker:{color:'#38bdf8'},text:yoyB.map(function(r){return r.count.toLocaleString();}),textposition:'outside'}],
      Object.assign({},dark,{title:'Beneficiaries by Year',xaxis:{title:'Year',gridcolor:gridColor},yaxis:{title:'Count',gridcolor:gridColor},height:350}),{responsive:true});
  }

  /* -- YoY Claims -- */
  var yoyC = REPORT_DATA.yoy_claims || [];
  if (yoyC.length) {
    Plotly.newPlot('chart-yoy-claims',[{x:yoyC.map(function(r){return String(r.year);}),y:yoyC.map(function(r){return r.count;}),type:'bar',marker:{color:'#a78bfa'},text:yoyC.map(function(r){return r.count.toLocaleString();}),textposition:'outside'}],
      Object.assign({},dark,{title:'Carrier Claims by Year',xaxis:{title:'Year',gridcolor:gridColor},yaxis:{title:'Claims',gridcolor:gridColor},height:350}),{responsive:true});
  }

  /* -- Financial Trends (grouped bar) -- */
  var ft = REPORT_DATA.financial_trends || [];
  if (ft.length) {
    var ftYears = ft.map(function(r){return String(r.year);});
    Plotly.newPlot('chart-financial-trends',[
      {name:'Inpatient',x:ftYears,y:ft.map(function(r){return r.inpatient;}),type:'bar',marker:{color:'#f87171'}},
      {name:'Outpatient',x:ftYears,y:ft.map(function(r){return r.outpatient;}),type:'bar',marker:{color:'#fbbf24'}},
      {name:'Carrier',x:ftYears,y:ft.map(function(r){return r.carrier;}),type:'bar',marker:{color:'#4ade80'}}
    ],Object.assign({},dark,{barmode:'group',title:'Medicare Reimbursement Totals by Year & Type',xaxis:{title:'Year',gridcolor:gridColor},yaxis:{title:'Total Reimbursement ($)',gridcolor:gridColor},legend:{bgcolor:'rgba(0,0,0,0)'},height:400,margin:{l:80,r:30,t:50,b:40}}),{responsive:true});
  }

  /* -- Financial Distribution (box plots) -- */
  var fd = REPORT_DATA.financial_distribution || {};
  if (fd.medicare_reimb && fd.medicare_reimb.length) {
    Plotly.newPlot('chart-financial-dist',[
      {y:fd.medicare_reimb,name:'Medicare Reimb',type:'box',marker:{color:'#4ade80'}},
      {y:fd.beneficiary_resp,name:'Beneficiary Resp',type:'box',marker:{color:'#fbbf24'}},
      {y:fd.primary_payer,name:'Primary Payer',type:'box',marker:{color:'#38bdf8'}}
    ],Object.assign({},dark,{title:'Carrier Payment Distribution (sample)',yaxis:{title:'Amount ($)',gridcolor:gridColor},showlegend:false,height:400,margin:{l:80,r:30,t:50,b:40}}),{responsive:true});
  }

  /* -- Chronic Conditions (line chart) -- */
  var cc = REPORT_DATA.chronic_conditions || {};
  if (cc.years && cc.conditions) {
    var ccColors = ['#f87171','#fb923c','#fbbf24','#a3e635','#4ade80','#2dd4bf','#38bdf8','#818cf8','#a78bfa','#f472b6','#e2e8f0'];
    var ccTraces = cc.conditions.map(function(c,i){
      return {x:cc.years.map(String),y:c.rates,mode:'lines+markers',name:c.condition,line:{color:ccColors[i%ccColors.length],width:2},marker:{size:6}};
    });
    Plotly.newPlot('chart-chronic',ccTraces,
      Object.assign({},dark,{title:'Chronic Condition Prevalence by Year (%)',xaxis:{title:'Year',gridcolor:gridColor},yaxis:{title:'Prevalence (%)',gridcolor:gridColor},legend:{bgcolor:'rgba(0,0,0,0)',font:{size:10}},height:400}),{responsive:true});
  }

  /* -- Sidebar active section highlighting (IntersectionObserver) -- */
  var sidebarLinks = document.querySelectorAll('#sidebar a[data-section]');
  var sectionIds = Array.from(sidebarLinks).map(function(a){return a.getAttribute('data-section');});
  var sectionEls = sectionIds.map(function(id){return document.getElementById(id);}).filter(Boolean);

  if (sectionEls.length && 'IntersectionObserver' in window) {
    var currentActive = null;
    var observer = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) {
          var id = entry.target.id;
          if (currentActive !== id) {
            currentActive = id;
            sidebarLinks.forEach(function(a) {
              a.classList.toggle('active', a.getAttribute('data-section') === id);
            });
          }
        }
      });
    }, { rootMargin: '-10% 0px -70% 0px', threshold: 0 });
    sectionEls.forEach(function(el) { observer.observe(el); });
  }

  /* -- Table sorting -- */
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
        pmt_cols = ["LINE_NCH_PMT_AMT_1", "LINE_BENE_PTB_DDCTBL_AMT_1",
                    "LINE_COINSRNC_AMT_1", "LINE_ALOWD_CHRG_AMT_1"]
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
        top_field = max(field_counts, key=field_counts.get) if field_counts else ""
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
    summary = {
        "total_beneficiaries": f"{total_benes:,}",
        "total_claims": f"{total_claims:,}",
        "total_checks": len(validations),
        "passed_checks": len(validations) - failed_count,
        "failed_checks": failed_count,
        "summary_years": summary_years,
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

    new_system_files = []
    new_system_path = ""
    if new_sys and "inventory" in new_sys:
        new_inventory = new_sys["inventory"]
        if con and new_inventory:
            new_inventory = _count_rows_for_inventory(con, new_inventory)
        new_system_files = _build_file_inventory(new_inventory)
        new_system_path = new_sys.get("source_dir", "")

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
        }
        for c in comparisons
    ]

    # Extract raw chart data series
    chart_data = _extract_chart_data(con)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "failed_validations": failed_validations,
        "validations": serialized_validations,
        "comparisons": serialized_comparisons,
        "profiles": serialized_profiles,
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

    # ── 4. Render HTML from data + embedded chart JSON ──
    dc = report_data["data_context"]
    template = Template(HTML_TEMPLATE)
    html = template.render(
        **report_data,
        chart_data_json=chart_data_json,
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
