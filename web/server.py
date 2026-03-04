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
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# ── App setup ──────────────────────────────────────────────────────
app = FastAPI(title="CMS Claims Comparison Pipeline", version="1.0.0")
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

            from src.pipeline.context import PipelineContext
            from src.runner import run_pipeline as _run_pipeline

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
