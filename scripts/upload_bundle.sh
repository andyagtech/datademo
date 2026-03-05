#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# Upload the latest bundle ZIP to S3 at a persistent URL.
#
# Usage:
#   ./scripts/upload_bundle.sh                    # auto-finds latest zip
#   ./scripts/upload_bundle.sh path/to/file.zip   # explicit file
# ─────────────────────────────────────────────────────────
set -euo pipefail

BUCKET="andy-barr-cmsdata-assessment"
S3_KEY="downloads/cmsdata-assessment_full.zip"
PROFILE="personal"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Find the bundle to upload
if [ $# -ge 1 ] && [ -f "$1" ]; then
  BUNDLE="$1"
else
  # Auto-find the newest full bundle in the project root
  BUNDLE=$(ls -t "$PROJECT_ROOT"/cmsdata-assessment_full_*.zip 2>/dev/null | head -1)
  if [ -z "$BUNDLE" ]; then
    echo "❌ No bundle found. Run ./scripts/bundle.sh first."
    exit 1
  fi
fi

SIZE=$(du -sh "$BUNDLE" | cut -f1)
echo "📤 Uploading ${BUNDLE} (${SIZE}) → s3://${BUCKET}/${S3_KEY}"

aws s3 cp "$BUNDLE" "s3://${BUCKET}/${S3_KEY}" \
  --profile "${PROFILE}" \
  --content-type "application/zip" \
  --content-disposition "attachment; filename=\"cmsdata-assessment_full.zip\""

REGION=$(aws s3api get-bucket-location --bucket "$BUCKET" --profile "${PROFILE}" --query LocationConstraint --output text 2>/dev/null || echo "us-east-1")
[ "$REGION" = "None" ] && REGION="us-east-1"

echo ""
echo "✅ Upload complete"
echo "   S3 URI:  s3://${BUCKET}/${S3_KEY}"
echo "   URL:     https://${BUCKET}.s3.${REGION}.amazonaws.com/${S3_KEY}"
echo "   Website: http://${BUCKET}.s3-website-${REGION}.amazonaws.com/${S3_KEY}"
