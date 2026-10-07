#!/usr/bin/env bash
# Unified Test & Verification Runner for Meetings App
# Runs backend pytest tests, CloudFormation validation, frontend PKCE tests, and quality gates.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "================================================================="
echo "  Meetings App - Full E2E & Acceptance Verification Suite"
echo "================================================================="

echo
echo "==> [1/5] Running Backend Unit & Auth Tests (24/24)..."
(cd backend && uv run pytest -v)

echo
echo "==> [2/5] Running Infrastructure & E2E Integration Suite (39 tests)..."
uv run --project backend pytest tests/ -v

echo
echo "==> [3/5] Running Frontend PKCE & OAuth Node Suite (7 tests)..."
node --test tests/test_frontend_pkce.mjs

echo
echo "==> [4/5] Running Linters & Infrastructure Static Analysis..."
make lint
make infra-lint

echo
echo "==> [5/5] Running Frontend Production Build (Typecheck & Bundler)..."
(cd frontend && npm run build)

echo
echo "================================================================="
echo "  ALL ACCEPTANCE CRITERIA & TEST SUITES PASSED SUCCESSFULLY!"
echo "================================================================="
