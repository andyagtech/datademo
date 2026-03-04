#!/bin/bash
set -e

echo "============================================"
echo "CMS Claims Data Comparison Pipeline"
echo "============================================"

# ── Step 1: Run the pipeline ──────────────────────────────
echo ""
echo "▶ Running pipeline..."
python -m src.main "$@"

# ── Step 2: Run tests ────────────────────────────────────
echo ""
echo "▶ Running tests..."
python -m pytest tests/ -q || true

# ── Step 3: Render markdown documentation ─────────────────
echo ""
echo "▶ Rendering documentation..."
python scripts/render_md_docs.py

# ── Step 4: Serve the web UI ─────────────────────────────
echo ""
echo "============================================"
echo "Pipeline complete! Starting web server..."
echo "Open http://localhost:8888 in your browser"
echo "============================================"
echo ""
python -m http.server 8888 --directory docs
