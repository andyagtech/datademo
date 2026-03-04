#!/bin/bash
#
# Teardown script for the CMS Claims Comparison Pipeline (AWS)
#
# Removes all AWS resources created by the SAM deployment:
#   - Empties and deletes S3 buckets (data + SAM artifacts)
#   - Deletes the CloudFormation stack (Lambda, Step Functions, API Gateway, IAM roles)
#   - Deletes ECR container images
#
# Usage:
#   scripts/teardown_cloud.sh                          # default: dev environment
#   scripts/teardown_cloud.sh --env prod               # production
#   scripts/teardown_cloud.sh --profile my-aws-profile # custom AWS profile
#
# This script is idempotent — safe to run multiple times.

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────
ENV="dev"
PROFILE=""
REGION="us-east-1"
STACK_NAME=""
NO_CONFIRM=false

# ── Parse arguments ────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --env)       ENV="$2"; shift 2 ;;
    --profile)   PROFILE="$2"; shift 2 ;;
    --region)    REGION="$2"; shift 2 ;;
    --stack)     STACK_NAME="$2"; shift 2 ;;
    --yes|-y)    NO_CONFIRM=true; shift ;;
    -h|--help)
      echo "Usage: $0 [--env dev|prod] [--profile NAME] [--region REGION] [--yes]"
      exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# Build stack name from environment if not explicitly set
if [ -z "$STACK_NAME" ]; then
  if [ "$ENV" = "dev" ]; then
    STACK_NAME="cms-claims-pipeline-dev"
  else
    STACK_NAME="cms-claims-pipeline-${ENV}"
  fi
fi

# Build AWS CLI profile flag
PROFILE_FLAG=""
if [ -n "$PROFILE" ]; then
  PROFILE_FLAG="--profile $PROFILE"
fi

AWS="aws $PROFILE_FLAG --region $REGION"

echo "============================================"
echo "CMS Claims Pipeline — Cloud Teardown"
echo "============================================"
echo ""
echo "  Stack:   $STACK_NAME"
echo "  Region:  $REGION"
echo "  Profile: ${PROFILE:-default}"
echo ""

# ── Confirm ────────────────────────────────────────────────
if [ "$NO_CONFIRM" = false ]; then
  read -p "This will DELETE all AWS resources for this stack. Continue? [y/N] " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
  fi
fi

# ── Step 1: Find and empty S3 buckets ─────────────────────
echo ""
echo "▶ Step 1: Finding S3 buckets..."

ACCOUNT_ID=$($AWS sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
if [ -z "$ACCOUNT_ID" ]; then
  echo "  ✗ Could not determine AWS account ID. Check your credentials."
  exit 1
fi

BUCKET_NAME="${ACCOUNT_ID}-cms-claims-pipeline-${ENV}"
echo "  Data bucket: $BUCKET_NAME"

if $AWS s3api head-bucket --bucket "$BUCKET_NAME" 2>/dev/null; then
  echo "  Emptying bucket..."
  $AWS s3 rm "s3://${BUCKET_NAME}" --recursive --quiet 2>/dev/null || true
  # Also delete versioned objects
  echo "  Removing versioned objects..."
  $AWS s3api list-object-versions --bucket "$BUCKET_NAME" --output json 2>/dev/null | \
    python3 -c "
import sys, json
data = json.load(sys.stdin)
objects = []
for v in data.get('Versions', []):
    objects.append({'Key': v['Key'], 'VersionId': v['VersionId']})
for d in data.get('DeleteMarkers', []):
    objects.append({'Key': d['Key'], 'VersionId': d['VersionId']})
if objects:
    # Delete in batches of 1000
    for i in range(0, len(objects), 1000):
        batch = objects[i:i+1000]
        print(json.dumps({'Objects': batch, 'Quiet': True}))
" 2>/dev/null | while read -r batch; do
    echo "$batch" | $AWS s3api delete-objects --bucket "$BUCKET_NAME" --delete file:///dev/stdin --quiet 2>/dev/null || true
  done
  echo "  ✓ Bucket emptied"
else
  echo "  (bucket does not exist — skipping)"
fi

# ── Step 2: Delete CloudFormation stack ───────────────────
echo ""
echo "▶ Step 2: Deleting CloudFormation stack..."

if $AWS cloudformation describe-stacks --stack-name "$STACK_NAME" >/dev/null 2>&1; then
  # SAM delete handles ECR cleanup too
  cd "$(dirname "$0")/../infra"
  sam delete \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    $PROFILE_FLAG \
    --no-prompts 2>&1 || true
  cd - >/dev/null
  echo "  ✓ Stack deletion initiated"

  # Wait for deletion
  echo "  Waiting for stack deletion..."
  $AWS cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" 2>/dev/null || true
  echo "  ✓ Stack deleted"
else
  echo "  (stack does not exist — skipping)"
fi

# ── Step 3: Clean up SAM artifacts bucket ─────────────────
echo ""
echo "▶ Step 3: Cleaning up SAM artifacts..."

# SAM creates a managed bucket for artifacts
SAM_BUCKET=$($AWS s3 ls 2>/dev/null | grep -o 'aws-sam-cli-managed-default[^ ]*' | head -1 || echo "")
if [ -n "$SAM_BUCKET" ]; then
  echo "  SAM bucket: $SAM_BUCKET"
  echo "  (Keeping SAM artifacts bucket — it may be shared with other stacks)"
else
  echo "  (No SAM artifacts bucket found)"
fi

# ── Done ──────────────────────────────────────────────────
echo ""
echo "============================================"
echo "✓ Teardown complete"
echo "============================================"
echo ""
echo "Removed:"
echo "  - CloudFormation stack: $STACK_NAME"
echo "  - S3 bucket: $BUCKET_NAME"
echo "  - Lambda functions, Step Functions, API Gateway, IAM roles"
echo ""
echo "Not removed (may be shared):"
echo "  - SAM CLI managed bucket"
echo "  - ECR repositories (sam delete handles these)"
echo ""
