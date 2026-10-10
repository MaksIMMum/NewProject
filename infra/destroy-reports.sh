#!/usr/bin/env bash
# Deletes the reports infrastructure stack.
set -euo pipefail

main() {
  cd "$(dirname "$0")/.."
  source infra/common.sh

  REPORTS_STACK="$PROJECT_NAME-reports"
  if ! stack_exists "$REPORTS_STACK"; then
    echo "Stack $REPORTS_STACK does not exist."
    exit 0
  fi

  bucket="$(output "$REPORTS_STACK" ReportsBucketName)"
  if [ -n "$bucket" ] && aws s3 ls "s3://$bucket" >/dev/null 2>&1; then
    echo "==> Emptying reports bucket s3://$bucket"
    aws s3 rm "s3://$bucket" --recursive
  fi

  echo "==> Deleting CloudFormation stack $REPORTS_STACK"
  aws cloudformation delete-stack --stack-name "$REPORTS_STACK"
  aws cloudformation wait stack-delete-complete --stack-name "$REPORTS_STACK"
  echo "==> Reports stack deleted."
}

main "$@"
