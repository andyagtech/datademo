#!/bin/bash
set -e

echo "============================================"
echo "CMS Claims Data Comparison Pipeline"
echo "============================================"

# ── Parse entrypoint-level flags ──
PIPELINE_ARGS=()
SKIP_TESTS=false
for arg in "$@"; do
    if [ "$arg" = "--skip-tests" ]; then
        SKIP_TESTS=true
    else
        PIPELINE_ARGS+=("$arg")
    fi
done

if [[ ! " ${PIPELINE_ARGS[*]} " =~ " --new-data " ]]; then
    NEW_SYSTEM_DIR="data/new_system"
    if [ -d "$NEW_SYSTEM_DIR" ] && ls "$NEW_SYSTEM_DIR"/*.csv 1>/dev/null 2>&1; then
        echo ""
        echo "▶ Auto-detected new system CSVs in $NEW_SYSTEM_DIR"
        PIPELINE_ARGS+=("--new-data" "$NEW_SYSTEM_DIR")
    fi
fi

# ── Step 1: Run the pipeline ──────────────────────────────
echo ""
echo "▶ Running pipeline..."
python -m src.main "${PIPELINE_ARGS[@]}"

# ── Step 2: Run tests ────────────────────────────────
if [ $SKIP_TESTS = false ]; then
    echo ""
    echo "▶ Running tests..."
    python -m pytest tests/ -q || true
else
    echo ""
    echo "Skipping tests..."
fi

# ── Step 3: Render markdown documentation ─────────────
echo ""
echo "▶ Rendering documentation..."
python scripts/render_md_docs.py

# ── Step 4: Serve the web UI ─────────────────────────
echo ""
echo "============================================"
echo "Pipeline complete! Starting web server..."
echo "Open http://localhost:8888 in your browser"
echo "============================================"
echo ""
python -m http.server 8888 --directory docs
