#!/usr/bin/env bash
# Deletes the AI stack.
set -euo pipefail

main() {
  cd "$(dirname "$0")/.."
  export PATH="${HOME}/.local/bin:${PATH}"
  source infra/common.sh

  AI_STACK="$PROJECT_NAME-ai"

  if ! stack_exists "$AI_STACK"; then
    echo "Stack $AI_STACK does not exist; nothing to do."
    exit 0
  fi

  echo "==> Deleting $AI_STACK..."
  aws cloudformation delete-stack --stack-name "$AI_STACK"
  aws cloudformation wait stack-delete-complete --stack-name "$AI_STACK"
  echo "    Done."
}

main "$@"
