"""
FastAPI web server for the CMS Claims Comparison Pipeline.

Provides:
- File upload endpoints (old system + new system CSVs)
- Pipeline execution with Server-Sent Events (SSE) progress streaming
- Report viewing (HTML + JSON)
- Self-contained HTML frontend served at /
"""

import asyncio
import json
import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# ── App setup ──────────────────────────────────────────────────────
app = FastAPI(title="CMS Claims Comparison Pipeline", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
logger = logging.getLogger("web")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Directory for pipeline run workspaces
WORKSPACE_DIR = Path(tempfile.gettempdir()) / "cms_pipeline_workspaces"
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

# Track active runs
_runs: dict[str, dict] = {}


# ── Frontend ───────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the self-contained upload UI."""
    return FRONTEND_HTML


# ── Upload endpoints ───────────────────────────────────────────────
@app.post("/api/upload/{system_type}")
async def upload_files(system_type: str, files: list[UploadFile] = File(...)):
    """Upload CSV files for old or new system.

    system_type: 'old' or 'new'
    """
    if system_type not in ("old", "new"):
        raise HTTPException(400, "system_type must be 'old' or 'new'")

    run_id = str(uuid.uuid4())[:8]
    workspace = WORKSPACE_DIR / run_id
    old_dir = workspace / "data" / "raw"
    new_dir = workspace / "data" / "new"
    old_dir.mkdir(parents=True, exist_ok=True)
    new_dir.mkdir(parents=True, exist_ok=True)

    target_dir = old_dir if system_type == "old" else new_dir

    saved = []
    for f in files:
        dest = target_dir / f.filename
        with open(dest, "wb") as out:
            content = await f.read()
            out.write(content)
        saved.append({"name": f.filename, "size_mb": round(len(content) / 1e6, 2)})
        logger.info(f"[{run_id}] Saved {f.filename} ({len(content)/1e6:.1f} MB) to {target_dir}")

    _runs[run_id] = {
        "workspace": str(workspace),
        "status": "uploaded",
        "system_type": system_type,
        "files": saved,
    }

    return {"run_id": run_id, "files": saved, "system_type": system_type}


@app.post("/api/upload/{run_id}/{system_type}")
async def upload_additional(run_id: str, system_type: str, files: list[UploadFile] = File(...)):
    """Upload additional files to an existing run (e.g., add new system data)."""
    if run_id not in _runs:
        raise HTTPException(404, f"Run {run_id} not found")
    if system_type not in ("old", "new"):
        raise HTTPException(400, "system_type must be 'old' or 'new'")

    workspace = Path(_runs[run_id]["workspace"])
    target_dir = workspace / "data" / ("raw" if system_type == "old" else "new")
    target_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for f in files:
        dest = target_dir / f.filename
        with open(dest, "wb") as out:
            content = await f.read()
            out.write(content)
        saved.append({"name": f.filename, "size_mb": round(len(content) / 1e6, 2)})

    _runs[run_id]["files"].extend(saved)
    return {"run_id": run_id, "files": saved, "system_type": system_type}


# ── Pipeline execution with SSE progress ───────────────────────────
@app.get("/api/run/{run_id}")
async def run_pipeline(run_id: str, request: Request):
    """Execute the pipeline and stream progress via SSE."""
    if run_id not in _runs:
        raise HTTPException(404, f"Run {run_id} not found")

    run = _runs[run_id]
    workspace = Path(run["workspace"])

    async def event_stream() -> AsyncGenerator[str, None]:
        yield f"data: {json.dumps({'type': 'status', 'message': 'Starting pipeline...'})}\n\n"

        try:
            # Import pipeline modules
            import sys
            project_root = str(Path(__file__).resolve().parent.parent)
            if project_root not in sys.path:
                sys.path.insert(0, project_root)

            from src.pipeline import PipelineContext
            from src.pipeline.runner import run_pipeline as _run_pipeline

            # Determine data paths
            old_data_dir = str(workspace / "data" / "raw")
            new_data_dir = workspace / "data" / "new"
            db_path = str(workspace / "data" / "db" / "cms_claims.duckdb")
            report_dir = workspace / "reports"
            report_dir.mkdir(parents=True, exist_ok=True)

            has_new = any(new_data_dir.glob("*.csv")) or any(new_data_dir.glob("*.zip"))
            new_data_str = str(new_data_dir) if has_new else None

            yield f"data: {json.dumps({'type': 'status', 'message': f'Found old system data in {old_data_dir}'})}\n\n"
            if new_data_str:
                yield f"data: {json.dumps({'type': 'status', 'message': f'Found new system data in {new_data_str}'})}\n\n"

            # Run pipeline in a thread to avoid blocking the event loop
            def _execute():
                import duckdb
                ctx = PipelineContext(
                    old_data_dir=old_data_dir,
                    new_data_dir=new_data_str,
                    db_path=db_path,
                )
                # Override report dir
                import src.report as report_mod
                original_report_dir = report_mod.REPORT_DIR
                report_mod.REPORT_DIR = report_dir
                try:
                    results = _run_pipeline(ctx)
                finally:
                    report_mod.REPORT_DIR = original_report_dir
                return results

            yield f"data: {json.dumps({'type': 'step', 'step': 1, 'message': 'Running pipeline (this takes ~60 seconds)...'})}\n\n"

            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, _execute)

            # Check for success
            report_html = report_dir / "comparison_report.html"
            report_json = report_dir / "report_data.json"

            if report_html.exists():
                _runs[run_id]["status"] = "complete"
                _runs[run_id]["report_html"] = str(report_html)
                _runs[run_id]["report_json"] = str(report_json) if report_json.exists() else None

                yield f"data: {json.dumps({'type': 'complete', 'message': 'Pipeline complete!', 'report_url': f'/api/report/{run_id}/html', 'json_url': f'/api/report/{run_id}/json'})}\n\n"
            else:
                _runs[run_id]["status"] = "failed"
                yield f"data: {json.dumps({'type': 'error', 'message': 'Pipeline completed but no report was generated.'})}\n\n"

        except Exception as e:
            _runs[run_id]["status"] = "failed"
            logger.exception(f"[{run_id}] Pipeline failed")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Report serving ─────────────────────────────────────────────────
@app.get("/api/report/{run_id}/html")
async def get_report_html(run_id: str):
    """Serve the generated HTML report."""
    if run_id not in _runs or "report_html" not in _runs.get(run_id, {}):
        raise HTTPException(404, "Report not found")
    return FileResponse(_runs[run_id]["report_html"], media_type="text/html")


@app.get("/api/report/{run_id}/json")
async def get_report_json(run_id: str):
    """Serve the generated JSON data."""
    if run_id not in _runs or not _runs.get(run_id, {}).get("report_json"):
        raise HTTPException(404, "Report JSON not found")
    return FileResponse(_runs[run_id]["report_json"], media_type="application/json")


@app.get("/api/runs")
async def list_runs():
    """List all pipeline runs."""
    return {
        run_id: {
            "status": r["status"],
            "files": r.get("files", []),
            "has_report": "report_html" in r,
        }
        for run_id, r in _runs.items()
    }


# ── Cleanup ────────────────────────────────────────────────────────
@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str):
    """Delete a pipeline run and its workspace."""
    if run_id not in _runs:
        raise HTTPException(404, f"Run {run_id} not found")
    workspace = Path(_runs[run_id]["workspace"])
    if workspace.exists():
        shutil.rmtree(workspace)
    del _runs[run_id]
    return {"deleted": run_id}


# ── AI Chat endpoint ──────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _PROJECT_ROOT / "data" / "database" / "cms_claims.duckdb"

_CMS_SYSTEM_PROMPT = """You are a data analysis assistant embedded in the CMS Claims Comparison Report.
You help reviewers understand the findings from comparing an old Medicare claims processing
system (CMS DE-SynPUF) against a new replacement system.

You have deep knowledge of:
- Medicare beneficiary summary data (demographics, chronic conditions, coverage months, financials)
- Carrier claims data (diagnosis codes, procedure codes, provider NPIs, payment line items)
- Data quality validation checks (key integrity, temporal consistency, demographic consistency, financial reconciliation)
- The specific discrepancies found in this comparison

## Key Findings You Know About
{findings_context}

## Database Access
You have direct access to the DuckDB database via the `query_database` tool.
Use it to answer questions that require looking at the actual data.
Always use SELECT queries only — the database is read-only.
Add LIMIT clauses (max 50 rows) to avoid huge result sets.

### Database Schema
**beneficiary_summary** / **new_beneficiary_summary** (old vs new system, 33 cols each):
  Key: DESYNPUF_ID (VARCHAR) + summary_year (INTEGER)
  Demographics: BENE_BIRTH_DT, BENE_DEATH_DT, BENE_SEX_IDENT_CD, BENE_RACE_CD, BENE_ESRD_IND
  Location: SP_STATE_CODE, BENE_COUNTY_CD
  Coverage: BENE_HI_CVRAGE_TOT_MONS, BENE_SMI_CVRAGE_TOT_MONS, BENE_HMO_CVRAGE_TOT_MONS, PLAN_CVRG_MOS_NUM
  Chronic conditions (1=yes, 2=no): SP_ALZHDMTA, SP_CHF, SP_CHRNKIDN, SP_CNCR, SP_COPD, SP_DEPRESSN, SP_DIABETES, SP_ISCHMCHT, SP_OSTEOPRS, SP_RA_OA, SP_STRKETIA
  Financials (DOUBLE): MEDREIMB_IP, BENRES_IP, PPPYMT_IP, MEDREIMB_OP, BENRES_OP, PPPYMT_OP, MEDREIMB_CAR, BENRES_CAR, PPPYMT_CAR

**carrier_claims** / **new_carrier_claims** (old vs new, 142 cols each):
  Key: CLM_ID (BIGINT in old, VARCHAR in new — cast to VARCHAR for joins), DESYNPUF_ID (VARCHAR)
  Dates: CLM_FROM_DT, CLM_THRU_DT (BIGINT, YYYYMMDD format)
  Diagnosis: ICD9_DGNS_CD_1..8, LINE_ICD9_DGNS_CD_1..13
  Providers: PRF_PHYSN_NPI_1..13, TAX_NUM_1..13
  Procedures: HCPCS_CD_1..13
  Payments (DOUBLE): LINE_NCH_PMT_AMT_1..13, LINE_BENE_PTB_DDCTBL_AMT_1..13, LINE_BENE_PRMRY_PYR_PD_AMT_1..13, LINE_COINSRNC_AMT_1..13, LINE_ALOWD_CHRG_AMT_1..13
  Processing: LINE_PRCSG_IND_CD_1..13

**_discrepancy_detail** (37 cols) — pre-computed per-beneficiary diffs:
  Key: DESYNPUF_ID, summary_year. diff_* columns (1 = mismatch), delta_* columns (dollar amount), total_diffs

**_financial_recon** (11 cols) — financial reconciliation:
  Key: DESYNPUF_ID, summary_year. reported_* vs calc_* columns, *_diff columns

**_match_beneficiary** / **_match_claims** — match status (matched/old_only/new_only)

### Important Notes
- "ZZ" prefix beneficiaries (DESYNPUF_ID LIKE 'ZZ%') are fabricated test records injected by the new system
- When comparing old vs new, join on: beneficiary_summary ON DESYNPUF_ID + summary_year; carrier_claims ON CLM_ID::VARCHAR
- The 0.90 payment ratio pattern: many new system payments = old * 0.90 (systematic 10% reduction)
- Dates are stored as BIGINT in YYYYMMDD format (e.g., 20080101)

## Guidelines
1. Be concise and data-driven. Use the query_database tool to verify claims with real data.
2. When asked about discrepancies, query the database to show concrete examples.
3. Explain technical terms (ICD-9, HCPCS, NPI, etc.) in plain language when asked.
4. Help reviewers understand the *impact* of each discrepancy.
5. Format responses with markdown. Show SQL queries you ran and summarize results in tables.
6. If a query returns too much data, summarize the key patterns.
"""

# OpenAI tool definition for query_database
_TOOL_QUERY_DATABASE = {
    "type": "function",
    "function": {
        "name": "query_database",
        "description": "Execute a read-only SQL query against the CMS claims DuckDB database. Use SELECT statements only. Always include a LIMIT clause (max 50 rows). Returns results as a list of row dictionaries.",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "The SQL SELECT query to execute. Must be read-only. Include LIMIT clause."
                },
                "explanation": {
                    "type": "string",
                    "description": "Plain-English explanation of what this query does, why you are running it, and what the results will tell us."
                }
            },
            "required": ["sql", "explanation"]
        }
    }
}

# Maximum rows returned per query, and max tool-call iterations per request
_MAX_ROWS = 50
_MAX_TOOL_ROUNDS = 5


def _execute_duckdb_query(sql: str) -> dict:
    """Execute a read-only SQL query against the CMS DuckDB database.

    Returns {"columns": [...], "rows": [[...], ...], "row_count": N, "truncated": bool}
    or {"error": "message"} on failure.
    """
    import duckdb

    if not _DB_PATH.exists():
        return {"error": f"Database not found at {_DB_PATH}. Run the pipeline first."}

    # Safety: reject non-SELECT statements
    sql_stripped = sql.strip().rstrip(";").strip()
    first_word = sql_stripped.split()[0].upper() if sql_stripped else ""
    if first_word not in ("SELECT", "WITH", "EXPLAIN", "DESCRIBE", "SHOW", "PRAGMA"):
        return {"error": f"Only SELECT/WITH/EXPLAIN/DESCRIBE queries are allowed. Got: {first_word}"}

    try:
        con = duckdb.connect(str(_DB_PATH), read_only=True)
        try:
            result = con.execute(sql_stripped)
            columns = [desc[0] for desc in result.description]
            rows = result.fetchmany(_MAX_ROWS + 1)
            truncated = len(rows) > _MAX_ROWS
            if truncated:
                rows = rows[:_MAX_ROWS]
            # Convert to JSON-safe types
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
        finally:
            con.close()
    except duckdb.Error as e:
        return {"error": f"SQL error: {str(e)}"}
    except Exception as e:
        return {"error": f"Query failed: {str(e)}"}


def _build_findings_context() -> str:
    """Load report_data.json and build a condensed findings summary for the system prompt."""
    report_json = _PROJECT_ROOT / "reports" / "report_data.json"
    if not report_json.exists():
        return "No report data available yet. The pipeline has not been run."

    try:
        data = json.loads(report_json.read_text())
    except Exception:
        return "Report data could not be loaded."

    lines = []
    s = data.get("summary", {})
    lines.append(f"- Total beneficiaries: {s.get('total_beneficiaries', 'N/A')}")
    lines.append(f"- Total carrier claims: {s.get('total_claims', 'N/A')}")
    lines.append(f"- Validation checks: {s.get('passed_checks', '?')}/{s.get('total_checks', '?')} passed")
    lines.append(f"- Claims payment discrepancy: {s.get('total_claims_pmt_divergence', 'N/A')}")
    lines.append(f"- Claims with payment changes: {s.get('claims_with_pmt_changes', 'N/A')}")
    lines.append(f"- Beneficiaries affected: {s.get('benes_with_any_change', 'N/A')}")

    # Summarize non-zero comparison checks
    comparisons = data.get("comparisons", [])
    nonzero = [c for c in comparisons if c.get("metric_value") not in (0, "0", None)]
    lines.append(f"- Total comparison checks: {len(comparisons)} ({len(nonzero)} with findings)")

    # Group by category
    by_cat: dict[str, list] = {}
    for c in nonzero:
        cat = c.get("category", "unknown")
        by_cat.setdefault(cat, []).append(c)

    for cat, checks in by_cat.items():
        lines.append(f"\n### {cat.replace('_', ' ').title()} Checks")
        for c in checks[:15]:  # cap to avoid prompt explosion
            name = c.get("check_name", "")
            val = c.get("metric_value", "")
            impact = c.get("impact", "")[:120]
            lines.append(f"  - {name}: {val} — {impact}")
        if len(checks) > 15:
            lines.append(f"  ... and {len(checks) - 15} more {cat} checks")

    # Failed validations
    failed = [v for v in data.get("validations", []) if not v.get("passed")]
    if failed:
        lines.append("\n### Failed Validation Checks")
        for v in failed:
            lines.append(f"  - {v.get('check_name', '')}: {v.get('issues_found', '')} issues — {v.get('description', '')}")

    return "\n".join(lines)


@app.post("/api/chat")
async def chat(request: Request):
    """AI chat endpoint with function calling for DuckDB queries."""
    try:
        import openai as openai_mod
    except ImportError:
        raise HTTPException(500, "openai package not installed. Run: pip install openai")

    import os
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(500, "OPENAI_API_KEY environment variable not set")

    body = await request.json()
    message = body.get("message", "").strip()
    conversation_history = body.get("conversationHistory", [])
    model = body.get("model", "gpt-4o")

    if not message:
        raise HTTPException(400, "message is required")

    # Build system prompt with live report data
    findings = _build_findings_context()
    system_prompt = _CMS_SYSTEM_PROMPT.format(findings_context=findings)

    messages = [
        {"role": "system", "content": system_prompt},
        *[{"role": m["role"], "content": m["content"]} for m in conversation_history],
        {"role": "user", "content": message},
    ]

    try:
        client = openai_mod.OpenAI(api_key=api_key)
        tools = [_TOOL_QUERY_DATABASE]
        sql_queries_run = []  # track for the response

        # Tool-calling loop: let the model call query_database up to N times
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

            # If no tool calls, we have the final answer
            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                content = choice.message.content or ""
                return {
                    "content": content,
                    "model": response.model or model,
                    "queries": sql_queries_run,
                }

            # Process tool calls
            messages.append(choice.message)  # add assistant message with tool_calls

            for tool_call in choice.message.tool_calls:
                if tool_call.function.name == "query_database":
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        args = {"sql": ""}

                    sql = args.get("sql", "")
                    explanation = args.get("explanation", "")
                    logger.info(f"[chat] query_database: {explanation} | SQL: {sql[:200]}")

                    # Execute the query
                    result = _execute_duckdb_query(sql)
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

                    # Send result back to the model
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, default=str),
                    })
                else:
                    # Unknown tool
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps({"error": f"Unknown tool: {tool_call.function.name}"}),
                    })

        # If we exhausted tool rounds, get final answer without tools
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=2000,
            temperature=0.4,
        )
        content = response.choices[0].message.content or ""
        return {
            "content": content,
            "model": response.model or model,
            "queries": sql_queries_run,
        }
    except Exception as e:
        logger.exception("Chat API error")
        raise HTTPException(500, f"Chat failed: {str(e)}")


# ── Frontend HTML ──────────────────────────────────────────────────
FRONTEND_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CMS Claims Comparison Pipeline</title>
<style>
  :root {
    --bg: #0f172a; --surface: #1e293b; --border: #334155;
    --text: #e2e8f0; --muted: #94a3b8; --accent: #38bdf8;
    --green: #4ade80; --red: #f87171; --yellow: #fbbf24;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }

  .container { max-width: 900px; margin: 0 auto; padding: 2rem 1.5rem; }

  h1 { font-size: 1.5rem; font-weight: 700; margin-bottom: 0.25rem; }
  .subtitle { color: var(--muted); font-size: 0.875rem; margin-bottom: 2rem; }

  .steps { display: flex; gap: 0; margin-bottom: 2rem; }
  .step { flex: 1; padding: 0.75rem 1rem; background: var(--surface); border: 1px solid var(--border);
          text-align: center; font-size: 0.8rem; color: var(--muted); position: relative; }
  .step:first-child { border-radius: 8px 0 0 8px; }
  .step:last-child { border-radius: 0 8px 8px 0; }
  .step.active { background: #1e3a5f; border-color: var(--accent); color: var(--text); }
  .step.done { background: #1a3a2a; border-color: var(--green); color: var(--green); }
  .step-num { font-weight: 700; font-size: 1rem; display: block; margin-bottom: 0.15rem; }

  .upload-zone {
    border: 2px dashed var(--border); border-radius: 12px; padding: 2.5rem 1.5rem;
    text-align: center; cursor: pointer; transition: all 0.2s;
    background: var(--surface); margin-bottom: 1.5rem;
  }
  .upload-zone:hover, .upload-zone.dragover {
    border-color: var(--accent); background: #1e3a5f;
  }
  .upload-zone h3 { font-size: 1rem; margin-bottom: 0.5rem; }
  .upload-zone p { color: var(--muted); font-size: 0.85rem; }
  .upload-zone .icon { font-size: 2rem; margin-bottom: 0.75rem; }
  .upload-zone input { display: none; }

  .file-list { list-style: none; margin-bottom: 1.5rem; }
  .file-list li {
    display: flex; align-items: center; justify-content: space-between;
    padding: 0.5rem 0.75rem; background: var(--surface); border-radius: 6px;
    margin-bottom: 0.35rem; font-size: 0.85rem;
  }
  .file-list .size { color: var(--muted); font-size: 0.8rem; }
  .file-list .check { color: var(--green); }

  .btn {
    display: inline-block; padding: 0.65rem 1.5rem; border: none; border-radius: 8px;
    font-size: 0.9rem; font-weight: 600; cursor: pointer; transition: all 0.15s;
  }
  .btn-primary { background: var(--accent); color: #0f172a; }
  .btn-primary:hover { background: #60ccf8; }
  .btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }
  .btn-secondary { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
  .btn-secondary:hover { border-color: var(--accent); }
  .btn-green { background: var(--green); color: #0f172a; }
  .btn-green:hover { background: #6ee7a0; }

  .btn-row { display: flex; gap: 0.75rem; align-items: center; margin-top: 1rem; }

  .log-box {
    background: #0d1117; border: 1px solid var(--border); border-radius: 8px;
    padding: 1rem; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.8rem;
    color: var(--muted); max-height: 300px; overflow-y: auto; margin-top: 1rem;
    line-height: 1.6;
  }
  .log-box .info { color: var(--accent); }
  .log-box .success { color: var(--green); }
  .log-box .error { color: var(--red); }
  .log-box .warn { color: var(--yellow); }

  .result-card {
    background: var(--surface); border: 1px solid var(--green); border-radius: 12px;
    padding: 1.5rem; text-align: center; margin-top: 1.5rem;
  }
  .result-card h3 { color: var(--green); margin-bottom: 0.5rem; }
  .result-card p { color: var(--muted); font-size: 0.85rem; margin-bottom: 1rem; }

  .hidden { display: none; }

  @media (max-width: 600px) {
    .steps { flex-direction: column; }
    .step:first-child { border-radius: 8px 8px 0 0; }
    .step:last-child { border-radius: 0 0 8px 8px; }
  }
</style>
</head>
<body>
<div class="container">
  <h1>CMS Claims Comparison Pipeline</h1>
  <p class="subtitle">Upload CSV files from two systems, run the comparison pipeline, and view the interactive report.</p>

  <!-- Progress steps -->
  <div class="steps">
    <div class="step active" id="step-1"><span class="step-num">1</span>Upload Old System</div>
    <div class="step" id="step-2"><span class="step-num">2</span>Upload New System</div>
    <div class="step" id="step-3"><span class="step-num">3</span>Run Pipeline</div>
    <div class="step" id="step-4"><span class="step-num">4</span>View Report</div>
  </div>

  <!-- Step 1: Upload old system -->
  <div id="panel-1">
    <div class="upload-zone" id="drop-old">
      <div class="icon">📂</div>
      <h3>Drop Old System CSVs Here</h3>
      <p>or click to browse — Beneficiary Summary + Carrier Claims files</p>
      <input type="file" id="input-old" multiple accept=".csv,.zip">
    </div>
    <ul class="file-list" id="files-old"></ul>
    <div class="btn-row">
      <button class="btn btn-primary" id="btn-upload-old" disabled>Upload & Continue</button>
    </div>
  </div>

  <!-- Step 2: Upload new system -->
  <div id="panel-2" class="hidden">
    <div class="upload-zone" id="drop-new">
      <div class="icon">📂</div>
      <h3>Drop New System CSVs Here</h3>
      <p>or click to browse — replacement system output files</p>
      <input type="file" id="input-new" multiple accept=".csv,.zip">
    </div>
    <ul class="file-list" id="files-new"></ul>
    <div class="btn-row">
      <button class="btn btn-primary" id="btn-upload-new" disabled>Upload & Continue</button>
      <button class="btn btn-secondary" id="btn-skip-new">Skip (old system only)</button>
    </div>
  </div>

  <!-- Step 3: Run pipeline -->
  <div id="panel-3" class="hidden">
    <button class="btn btn-green" id="btn-run" style="width:100%;padding:1rem;font-size:1rem;">
      ▶ Run Comparison Pipeline
    </button>
    <div class="log-box hidden" id="log-box"></div>
  </div>

  <!-- Step 4: Results -->
  <div id="panel-4" class="hidden">
    <div class="result-card">
      <h3>✓ Pipeline Complete</h3>
      <p>Your comparison report is ready.</p>
      <div class="btn-row" style="justify-content:center;">
        <a class="btn btn-green" id="btn-view-report" href="#" target="_blank">Open HTML Report</a>
        <a class="btn btn-secondary" id="btn-download-json" href="#" target="_blank">Download JSON Data</a>
        <button class="btn btn-secondary" id="btn-restart">New Comparison</button>
      </div>
    </div>
  </div>
</div>

<script>
(function() {
  var runId = null;
  var oldFiles = [];
  var newFiles = [];

  // DOM refs
  var panels = [1,2,3,4].map(function(n){return document.getElementById('panel-'+n);});
  var steps = [1,2,3,4].map(function(n){return document.getElementById('step-'+n);});
  var dropOld = document.getElementById('drop-old');
  var dropNew = document.getElementById('drop-new');
  var inputOld = document.getElementById('input-old');
  var inputNew = document.getElementById('input-new');
  var filesOldList = document.getElementById('files-old');
  var filesNewList = document.getElementById('files-new');
  var btnUploadOld = document.getElementById('btn-upload-old');
  var btnUploadNew = document.getElementById('btn-upload-new');
  var btnSkipNew = document.getElementById('btn-skip-new');
  var btnRun = document.getElementById('btn-run');
  var logBox = document.getElementById('log-box');

  function showStep(n) {
    panels.forEach(function(p,i){p.classList.toggle('hidden', i !== n-1);});
    steps.forEach(function(s,i){
      s.classList.remove('active','done');
      if (i < n-1) s.classList.add('done');
      if (i === n-1) s.classList.add('active');
    });
  }

  function renderFiles(list, files) {
    list.innerHTML = '';
    files.forEach(function(f){
      var li = document.createElement('li');
      li.innerHTML = '<span class="check">✓</span> <span>' + f.name + '</span> <span class="size">' + (f.size/1e6).toFixed(1) + ' MB</span>';
      list.appendChild(li);
    });
  }

  // Drag & drop helpers
  function setupDrop(zone, input, fileArr, btn) {
    zone.addEventListener('click', function(){input.click();});
    zone.addEventListener('dragover', function(e){e.preventDefault();zone.classList.add('dragover');});
    zone.addEventListener('dragleave', function(){zone.classList.remove('dragover');});
    zone.addEventListener('drop', function(e){
      e.preventDefault(); zone.classList.remove('dragover');
      var dt = e.dataTransfer;
      if (dt.files.length) { addFiles(dt.files, fileArr, zone, btn); }
    });
    input.addEventListener('change', function(){
      if (input.files.length) { addFiles(input.files, fileArr, zone, btn); }
    });
  }

  function addFiles(fileList, arr, zone, btn) {
    for (var i = 0; i < fileList.length; i++) arr.push(fileList[i]);
    var listEl = zone.parentNode.querySelector('.file-list');
    renderFiles(listEl, arr);
    btn.disabled = false;
  }

  setupDrop(dropOld, inputOld, oldFiles, btnUploadOld);
  setupDrop(dropNew, inputNew, newFiles, btnUploadNew);

  // Upload old system
  btnUploadOld.addEventListener('click', async function(){
    btnUploadOld.disabled = true;
    btnUploadOld.textContent = 'Uploading...';
    var fd = new FormData();
    oldFiles.forEach(function(f){fd.append('files', f);});
    try {
      var res = await fetch('/api/upload/old', {method:'POST', body:fd});
      var data = await res.json();
      runId = data.run_id;
      showStep(2);
    } catch(e) {
      alert('Upload failed: ' + e.message);
      btnUploadOld.disabled = false;
      btnUploadOld.textContent = 'Upload & Continue';
    }
  });

  // Upload new system
  btnUploadNew.addEventListener('click', async function(){
    btnUploadNew.disabled = true;
    btnUploadNew.textContent = 'Uploading...';
    var fd = new FormData();
    newFiles.forEach(function(f){fd.append('files', f);});
    try {
      await fetch('/api/upload/' + runId + '/new', {method:'POST', body:fd});
      showStep(3);
    } catch(e) {
      alert('Upload failed: ' + e.message);
      btnUploadNew.disabled = false;
      btnUploadNew.textContent = 'Upload & Continue';
    }
  });

  // Skip new system
  btnSkipNew.addEventListener('click', function(){showStep(3);});

  // Run pipeline
  btnRun.addEventListener('click', function(){
    btnRun.disabled = true;
    btnRun.textContent = 'Running...';
    logBox.classList.remove('hidden');
    logBox.innerHTML = '';

    var es = new EventSource('/api/run/' + runId);
    es.onmessage = function(e) {
      var msg = JSON.parse(e.data);
      var cls = msg.type === 'error' ? 'error' : msg.type === 'complete' ? 'success' : 'info';
      logBox.innerHTML += '<div class="' + cls + '">' + msg.message + '</div>';
      logBox.scrollTop = logBox.scrollHeight;

      if (msg.type === 'complete') {
        es.close();
        document.getElementById('btn-view-report').href = msg.report_url;
        document.getElementById('btn-download-json').href = msg.json_url;
        showStep(4);
      }
      if (msg.type === 'error') {
        es.close();
        btnRun.disabled = false;
        btnRun.textContent = '▶ Retry Pipeline';
      }
    };
    es.onerror = function() {
      es.close();
      logBox.innerHTML += '<div class="error">Connection lost. Check server logs.</div>';
      btnRun.disabled = false;
      btnRun.textContent = '▶ Retry Pipeline';
    };
  });

  // Restart
  document.getElementById('btn-restart').addEventListener('click', function(){
    runId = null; oldFiles = []; newFiles = [];
    filesOldList.innerHTML = ''; filesNewList.innerHTML = '';
    btnUploadOld.disabled = true; btnUploadOld.textContent = 'Upload & Continue';
    btnUploadNew.disabled = true; btnUploadNew.textContent = 'Upload & Continue';
    btnRun.disabled = false; btnRun.textContent = '▶ Run Comparison Pipeline';
    logBox.classList.add('hidden'); logBox.innerHTML = '';
    showStep(1);
  });
})();
</script>
</body>
</html>
"""
