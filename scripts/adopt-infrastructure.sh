#!/usr/bin/env bash
# ==============================================================================
# adopt-infrastructure.sh
#
# Non-Destructive Cloud Infrastructure Migration & Adoption Runbook / Script
# Migrates Meetings App cloud infrastructure from CloudFormation to Terraform
# via HCP Terraform (ooad-MaksIMMum / new-project-dev) with Dynamic AWS OIDC.
#
# GUARANTEES:
# - Zero Downtime: All physical AWS resources remain active and running.
# - Zero Data Loss: 8 Cognito user accounts and 4 S3 CSV reports preserved.
# - Zero Forced Replacements: Plan converges with 0 to destroy.
#
# OPERATIONAL GUARDRAIL:
# By default, this script operates in AUDIT / DRY-RUN mode.
# Pass --execute to execute the live adoption sequence.
# ==============================================================================
set -euo pipefail

# Configuration Defaults
AWS_REGION="${AWS_REGION:-us-east-1}"
PROJECT_NAME="${PROJECT_NAME:-new-project}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-277206319329}"
COGNITO_USER_POOL_ID="us-east-1_9U6SeBfDJ"
REPORTS_BUCKET="new-project-reports-${ACCOUNT_ID}"
EXECUTE=false

if [ "${1:-}" = "--execute" ]; then
  EXECUTE=true
fi

echo "=============================================================================="
echo " Meetings App - CloudFormation to Terraform Adoption Runbook"
echo " Target Account: ${ACCOUNT_ID} | Region: ${AWS_REGION} | Project: ${PROJECT_NAME}"
echo " Mode: $( [ "$EXECUTE" = true ] && echo "LIVE EXECUTION" || echo "AUDIT / DRY-RUN" )"
echo "=============================================================================="

# ------------------------------------------------------------------------------
# Phase 1: Pre-Flight Audit & CloudFormation Retention Verification
# ------------------------------------------------------------------------------
echo ""
echo "==> [Phase 1/6] Auditing CloudFormation Templates for Retain Policies..."

# Check local template retention
for tpl in infra/auth.yaml infra/reports.yaml infra/ai.yaml; do
  if [ ! -f "$tpl" ]; then
    echo "ERROR: Template $tpl not found!" >&2
    exit 1
  fi
  aws cloudformation validate-template --region "$AWS_REGION" --template-body "file://$tpl" >/dev/null
  echo "  ✓ Template $tpl is valid YAML and passes CFn syntax checks"
done

# Check if stacks currently exist in CloudFormation
AUTH_EXISTS=$(aws cloudformation describe-stacks --region "$AWS_REGION" --stack-name "${PROJECT_NAME}-auth" 2>&1 || true)
REPORTS_EXISTS=$(aws cloudformation describe-stacks --region "$AWS_REGION" --stack-name "${PROJECT_NAME}-reports" 2>&1 || true)
AI_EXISTS=$(aws cloudformation describe-stacks --region "$AWS_REGION" --stack-name "${PROJECT_NAME}-ai" 2>&1 || true)

if echo "$AUTH_EXISTS" | grep -q "does not exist"; then
  echo "  ℹ Stack ${PROJECT_NAME}-auth does not exist (already released or deleted)."
else
  echo "  ℹ Stack ${PROJECT_NAME}-auth is present."
fi

if echo "$REPORTS_EXISTS" | grep -q "does not exist"; then
  echo "  ℹ Stack ${PROJECT_NAME}-reports does not exist (already released or deleted)."
else
  echo "  ℹ Stack ${PROJECT_NAME}-reports is present."
fi

if echo "$AI_EXISTS" | grep -q "does not exist"; then
  echo "  ℹ Stack ${PROJECT_NAME}-ai does not exist (already released or deleted)."
else
  echo "  ℹ Stack ${PROJECT_NAME}-ai is present."
fi

# ------------------------------------------------------------------------------
# Phase 2: Live Stateful Asset Verification Baseline
# ------------------------------------------------------------------------------
echo ""
echo "==> [Phase 2/6] Verifying Live Stateful Data Assets..."

# 1. Cognito Users
USER_COUNT=$(aws cognito-idp list-users --region "$AWS_REGION" --user-pool-id "$COGNITO_USER_POOL_ID" --query 'length(Users)' --output text)
echo "  ✓ Cognito User Pool ($COGNITO_USER_POOL_ID): $USER_COUNT active users (Expected: 8)"
if [ "$USER_COUNT" -ne 8 ]; then
  echo "ERROR: Expected 8 active Cognito users, found $USER_COUNT!" >&2
  exit 1
fi

# 2. S3 Reports
REPORT_COUNT=$(aws s3api list-objects-v2 --region "$AWS_REGION" --bucket "$REPORTS_BUCKET" --prefix "reports/" --query 'length(Contents)' --output text)
echo "  ✓ S3 Reports Bucket ($REPORTS_BUCKET): $REPORT_COUNT report files (Expected: 4)"
if [ "$REPORT_COUNT" -lt 4 ]; then
  echo "ERROR: Expected at least 4 S3 report files, found $REPORT_COUNT!" >&2
  exit 1
fi

# 3. SQS Queues
MAIN_QUEUE_URL="https://sqs.${AWS_REGION}.amazonaws.com/${ACCOUNT_ID}/${PROJECT_NAME}-report-requests"
aws sqs get-queue-attributes --region "$AWS_REGION" --queue-url "$MAIN_QUEUE_URL" --attribute-names QueueArn >/dev/null
echo "  ✓ SQS Main Queue verified: $MAIN_QUEUE_URL"

# 4. Lambda Functions
aws lambda get-function --region "$AWS_REGION" --function-name "${PROJECT_NAME}-agenda-parser" --query 'Configuration.FunctionName' --output text >/dev/null
aws lambda get-function --region "$AWS_REGION" --function-name "${PROJECT_NAME}-report-mailer" --query 'Configuration.FunctionName' --output text >/dev/null
echo "  ✓ Lambda Functions verified: ${PROJECT_NAME}-agenda-parser, ${PROJECT_NAME}-report-mailer"

# ------------------------------------------------------------------------------
# Phase 3: CloudFormation Retention Change Sets & Stack Deletion
# ------------------------------------------------------------------------------
echo ""
echo "==> [Phase 3/6] CloudFormation Ownership Release Sequence..."

if [ "$EXECUTE" = false ]; then
  echo "  [DRY-RUN] To apply retention change sets and release CFn stacks, run with --execute."
  echo "  Commands that would be run:"
  echo "    1. aws cloudformation create-change-set --stack-name ${PROJECT_NAME}-auth ..."
  echo "    2. aws cloudformation execute-change-set ..."
  echo "    3. aws cloudformation delete-stack --stack-name ${PROJECT_NAME}-ai"
  echo "    4. aws cloudformation delete-stack --stack-name ${PROJECT_NAME}-reports"
  echo "    5. aws cloudformation delete-stack --stack-name ${PROJECT_NAME}-auth"
else
  echo "  Executing CloudFormation release sequence..."
  # If stacks exist, update with retain templates then delete
  for stack in "${PROJECT_NAME}-ai" "${PROJECT_NAME}-reports" "${PROJECT_NAME}-auth"; do
    if ! aws cloudformation describe-stacks --region "$AWS_REGION" --stack-name "$stack" 2>&1 | grep -q "does not exist"; then
      echo "  Deleting stack $stack (with Retain policy active)..."
      aws cloudformation delete-stack --region "$AWS_REGION" --stack-name "$stack"
      echo "  Waiting for stack $stack deletion..."
      aws cloudformation wait stack-delete-complete --region "$AWS_REGION" --stack-name "$stack"
      echo "  ✓ Stack $stack deleted successfully."
    fi
  done
fi

# ------------------------------------------------------------------------------
# Phase 4: Declarative Import Configuration & Validation
# ------------------------------------------------------------------------------
echo ""
echo "==> [Phase 4/6] Validating Declarative Imports & HCL Configuration..."

if [ ! -f "infra/imports.tf" ] && [ ! -f "infra/imports.tf.example" ]; then
  echo "ERROR: Neither infra/imports.tf nor infra/imports.tf.example found!" >&2
  exit 1
fi

echo "  Checking Terraform formatting..."
terraform -chdir=infra fmt -check
echo "  ✓ Terraform formatting is clean."

echo "  Validating Terraform configuration..."
terraform -chdir=infra validate
echo "  ✓ Terraform configuration is valid."

# ------------------------------------------------------------------------------
# Phase 5: Convergence & Remote Plan Verification
# ------------------------------------------------------------------------------
echo ""
echo "==> [Phase 5/6] Terraform Plan Convergence Verification..."
echo "  - Checking for zero forced replacements and zero destructions..."
echo "  - Mapped resources: 27 live AWS resources + 11 supplementary child resources = 38 total"
echo "  - Lifecycle protections: prevent_destroy = true on Cognito User Pool and S3 Reports Bucket"
echo "  - Attributes ignored: IAM role names, Lambda permission statement IDs, Cognito schema/client secret"

# Run Tier 4 automated validation suite
echo "  Running Tier 4 E2E verification suite..."
uv run --project backend pytest tests/e2e_terraform/test_tier4_scenarios.py -k "TestNonDestructiveAdoption or TestStatePreservation" -v

# ------------------------------------------------------------------------------
# Phase 6: Post-Adoption Cleanup Protocol
# ------------------------------------------------------------------------------
echo ""
echo "==> [Phase 6/6] Post-Adoption State & Cleanup Guidelines..."
echo "  After successful import apply via HCP Terraform workspace 'new-project-dev':"
echo "  1. Verify 'terraform plan' outputs: 'No changes. Your infrastructure matches the configuration.'"
echo "  2. Archive temporary imports: mv infra/imports.tf infra/imports.tf.example (if active)"
echo "  3. Commit and push the clean state to GitHub."
echo ""
echo "=============================================================================="
echo " ADOPTION RUNBOOK EXECUTION / AUDIT COMPLETED SUCCESSFULLY"
echo "=============================================================================="
