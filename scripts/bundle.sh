#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# Bundle the CMS Claims Comparison Pipeline for submission.
#
# Usage:
#   ./scripts/bundle.sh              # Everything (code + data)
#   ./scripts/bundle.sh --code-only  # Code, docs, reports (no data)
#   ./scripts/bundle.sh --data-only  # Data files only
# ─────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
MODE="${1:-all}"

case "$MODE" in
  --code-only)
    ARCHIVE_NAME="cmsdata-assessment_code_${TIMESTAMP}.zip"
    echo "📦 Bundling CODE ONLY → ${ARCHIVE_NAME}"
    cd "$PROJECT_ROOT"
    zip -r "$ARCHIVE_NAME" . \
      -x ".git/*" \
      -x ".venv*/*" \
      -x "__pycache__/*" \
      -x "*/__pycache__/*" \
      -x "*.pyc" \
      -x ".mypy_cache/*" \
      -x ".pytest_cache/*" \
      -x "*/.pytest_cache/*" \
      -x "data/old_system/*.csv" \
      -x "data/new_system/*.csv" \
      -x "data/original_downloads/*.zip" \
      -x "data/database/*.duckdb" \
      -x "data/database/*.wal" \
      -x "data/new_claims_system_outputs/*" \
      -x "reports/exports/*" \
      -x "node_modules/*"
    ;;

  --data-only)
    ARCHIVE_NAME="cmsdata-assessment_data_${TIMESTAMP}.zip"
    echo "📦 Bundling DATA ONLY → ${ARCHIVE_NAME}"
    cd "$PROJECT_ROOT"
    zip -r "$ARCHIVE_NAME" \
      data/old_system/ \
      data/new_system/ \
      data/original_downloads/ \
      data/new_claims_system_outputs/ \
      -x "*.gitkeep" \
      2>/dev/null || true

    # Also include the DuckDB database if it exists
    if [ -f data/database/cms_claims.duckdb ]; then
      zip -u "$ARCHIVE_NAME" data/database/cms_claims.duckdb
    fi
    ;;

  --all|*)
    ARCHIVE_NAME="cmsdata-assessment_full_${TIMESTAMP}.zip"
    echo "📦 Bundling EVERYTHING (code + data) → ${ARCHIVE_NAME}"
    cd "$PROJECT_ROOT"
    zip -r "$ARCHIVE_NAME" . \
      -x ".git/*" \
      -x ".venv*/*" \
      -x "__pycache__/*" \
      -x "*/__pycache__/*" \
      -x "*.pyc" \
      -x ".mypy_cache/*" \
      -x ".pytest_cache/*" \
      -x "*/.pytest_cache/*" \
      -x "reports/exports/*" \
      -x "node_modules/*"
    ;;
esac

SIZE=$(du -sh "$PROJECT_ROOT/$ARCHIVE_NAME" | cut -f1)
echo ""
echo "✅ Created: ${ARCHIVE_NAME} (${SIZE})"
echo "   Location: ${PROJECT_ROOT}/${ARCHIVE_NAME}"
