#!/usr/bin/env bash
# Minimal local web server for browsing reports and documentation.
# Uses Python's built-in http.server — no extra dependencies needed.
#
# Usage:
#   ./scripts/serve.sh          # defaults to port 8888
#   ./scripts/serve.sh 9000     # custom port
set -euo pipefail

PORT="${1:-8888}"
DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "──────────────────────────────────────────────"
echo "  Serving project at http://localhost:${PORT}"
echo "  Press Ctrl+C to stop"
echo "──────────────────────────────────────────────"
echo ""
echo "  Quick links:"
echo "    Report:  http://localhost:${PORT}/reports/comparison_report.html"
echo "    Docs:    http://localhost:${PORT}/docs/index.html"
echo ""

python3 -m http.server "$PORT" --directory "$DIR" --bind 127.0.0.1
