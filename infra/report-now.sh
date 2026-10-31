#!/usr/bin/env bash
# Trigger an on-demand report generation via SQS.
set -euo pipefail

main() {
  cd "$(dirname "$0")/.."
  source infra/common.sh

  REPORTS_STACK="$PROJECT_NAME-reports"
  queue_url="$(output "$REPORTS_STACK" ReportRequestsQueueUrl)"
  if [ -z "$queue_url" ] || [ "$queue_url" = "None" ]; then
    queue_url="$(aws sqs get-queue-url --queue-name "$PROJECT_NAME-report-requests" --query QueueUrl --output text 2>/dev/null || true)"
  fi
  if [ -z "$queue_url" ]; then
    echo "Could not find ReportRequestsQueueUrl for $PROJECT_NAME." >&2
    exit 1
  fi

  # Default week to previous ISO week if not provided as argument
  WEEK="${1:-${WEEK:-}}"
  if [ -z "$WEEK" ]; then
    WEEK="$(python3 -c '
from datetime import datetime, timezone, timedelta
prev_date = datetime.now(timezone.utc).date() - timedelta(days=7)
y, w, _ = prev_date.isocalendar()
print(f"{y}-W{w:02d}")
')"
  fi

  payload="{\"week\": \"$WEEK\", \"source\": \"manual\"}"
  echo "==> Sending report request to SQS: $payload"
  msg_id="$(aws sqs send-message \
    --queue-url "$queue_url" \
    --message-body "$payload" \
    --query "MessageId" \
    --output text)"

  echo "==> Message sent successfully! MessageId: $msg_id"
  echo "    Target week: $WEEK"
  echo "    Queue URL:   $queue_url"
}

main "$@"
