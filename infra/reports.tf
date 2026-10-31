# ==============================================================================
# S3 Reports Storage & Decoupled Notification Pipeline
# ==============================================================================

# 1. Reports S3 Bucket (Retained & Protected)
resource "aws_s3_bucket" "reports" {
  bucket = "${var.project_name}-reports-${data.aws_caller_identity.current.account_id}"

  tags = {
    PROJECT_NAME = var.project_name
  }

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [tags, tags_all]
  }
}

# S3 Default Encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# S3 Lifecycle Rule (90-day retention for CSV reports)
resource "aws_s3_bucket_lifecycle_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    id     = "ExpireReportsAfter90Days"
    status = "Enabled"

    filter {
      prefix = "reports/"
    }

    expiration {
      days = 90
    }
  }
}

# 2. S3 VPC Gateway Endpoint (Allows VPC Lambda to reach S3 without NAT)
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.route_table_id != "" ? [var.route_table_id] : []

  tags = {
    PROJECT_NAME = var.project_name
  }
}

# ==============================================================================
# SQS Queues (Main Request Queue & Dead-Letter Queue)
# ==============================================================================

# 3. Report Requests DLQ (14 days retention)
resource "aws_sqs_queue" "report_requests_dlq" {
  name                      = "${var.project_name}-report-requests-dlq"
  message_retention_seconds = 1209600

  tags = {
    PROJECT_NAME = var.project_name
  }
}

# 4. Report Requests Queue (360s visibility timeout, redrive to DLQ after 3 failures)
resource "aws_sqs_queue" "report_requests" {
  name                       = "${var.project_name}-report-requests"
  visibility_timeout_seconds = 360

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.report_requests_dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    PROJECT_NAME = var.project_name
  }
}

# ==============================================================================
# EventBridge Scheduler (Weekly Cron Schedule)
# ==============================================================================

# 5. Scheduler Execution Role & Policy
resource "aws_iam_role" "scheduler_role" {
  name = "${var.project_name}-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "scheduler.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    PROJECT_NAME = var.project_name
  }

  lifecycle {
    ignore_changes = [name, tags, tags_all]
  }
}

resource "aws_iam_role_policy" "scheduler_policy" {
  name = "SendReportRequests"
  role = aws_iam_role.scheduler_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = aws_sqs_queue.report_requests.arn
      }
    ]
  })
}

# 6. EventBridge Schedule (Every Monday at 07:00 Kyiv time)
resource "aws_scheduler_schedule" "weekly_report" {
  name                         = "${var.project_name}-weekly-report"
  schedule_expression          = "cron(0 7 ? * MON *)"
  schedule_expression_timezone = "Europe/Kyiv"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_sqs_queue.report_requests.arn
    role_arn = aws_iam_role.scheduler_role.arn
    input = jsonencode({
      week   = null
      source = "schedule"
    })
  }
}

# ==============================================================================
# Report Builder Lambda (VPC Container Image)
# ==============================================================================

# 7. CloudWatch Log Group for Report Builder
resource "aws_cloudwatch_log_group" "report_builder" {
  name              = "/aws/lambda/${var.project_name}-report-builder"
  retention_in_days = 7

  tags = {
    PROJECT_NAME = var.project_name
  }
}

# 8. Report Builder IAM Role & Policies
resource "aws_iam_role" "report_builder_role" {
  name = "${var.project_name}-report-builder-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    PROJECT_NAME = var.project_name
  }

  lifecycle {
    ignore_changes = [name, tags, tags_all]
  }
}

resource "aws_iam_role_policy_attachment" "report_builder_vpc" {
  role       = aws_iam_role.report_builder_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy_attachment" "report_builder_sqs" {
  role       = aws_iam_role.report_builder_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaSQSQueueExecutionRole"
}

resource "aws_iam_role_policy" "report_builder_policy" {
  name = "S3ReportWriter"
  role = aws_iam_role.report_builder_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.reports.arn}/reports/*"
      }
    ]
  })
}

# 9. Report Builder Function
resource "aws_lambda_function" "report_builder" {
  function_name = "${var.project_name}-report-builder"
  package_type  = "Image"
  image_uri     = var.image_uri
  role          = aws_iam_role.report_builder_role.arn
  timeout       = 60
  memory_size   = 512

  image_config {
    command = ["app.reports.lambda_handler.handler"]
  }

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = var.security_group_id != "" ? [var.security_group_id] : []
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.report_builder.name
  }

  environment {
    variables = {
      DATABASE_URL    = var.database_url
      REPORTS_BUCKET  = aws_s3_bucket.reports.id
      DB_POOL_SIZE    = "1"
      DB_MAX_OVERFLOW = "1"
      AWS_LWA_ENABLE  = "false"
    }
  }

  tags = {
    PROJECT_NAME = var.project_name
  }

  depends_on = [
    aws_cloudwatch_log_group.report_builder,
    aws_iam_role_policy_attachment.report_builder_vpc,
    aws_iam_role_policy_attachment.report_builder_sqs,
  ]
}

# 10. Lambda SQS Event Source Mapping (BatchSize = 1)
resource "aws_lambda_event_source_mapping" "report_builder_sqs" {
  event_source_arn = aws_sqs_queue.report_requests.arn
  function_name    = aws_lambda_function.report_builder.arn
  batch_size       = 1
  enabled          = true
}

# ==============================================================================
# Report Mailer Lambda (Python 3.12 Inline Script & SES Dispatcher)
# ==============================================================================

# 11. CloudWatch Log Group for Report Mailer
resource "aws_cloudwatch_log_group" "report_mailer" {
  name              = "/aws/lambda/${var.project_name}-report-mailer"
  retention_in_days = 7

  tags = {
    PROJECT_NAME = var.project_name
  }
}

# 12. Report Mailer IAM Role & Policies
resource "aws_iam_role" "report_mailer_role" {
  name = "${var.project_name}-report-mailer-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    PROJECT_NAME = var.project_name
  }

  lifecycle {
    ignore_changes = [name, tags, tags_all]
  }
}

resource "aws_iam_role_policy_attachment" "report_mailer_basic" {
  role       = aws_iam_role.report_mailer_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "report_mailer_policy" {
  name = "MailerPermissions"
  role = aws_iam_role.report_mailer_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.reports.arn}/reports/*"
      },
      {
        Effect = "Allow"
        Action = [
          "ses:SendEmail",
          "ses:SendRawEmail"
        ]
        Resource = "*"
      }
    ]
  })
}

# Package Inline Python Mailer Code into Zip Artifact
data "archive_file" "report_mailer_zip" {
  type        = "zip"
  output_path = "${path.module}/report_mailer.zip"

  source {
    content  = <<EOF
import json
import logging
import os
import urllib.parse
from email.message import EmailMessage
import boto3

logger = logging.getLogger("report-mailer")
logger.setLevel(logging.INFO)

s3_client = boto3.client("s3")
ses_client = boto3.client("sesv2")

def handler(event, context):
    logger.info("report-mailer invoked: event=%s", json.dumps(event))
    records = event.get("Records", [])
    if not records:
        logger.warning("No records found in event")
        return {"status": "no_records"}

    sender = os.environ.get("SENDER_EMAIL")
    recipient = os.environ.get("RECIPIENT_EMAIL")

    for record in records:
        s3_info = record.get("s3", {})
        bucket = s3_info.get("bucket", {}).get("name")
        raw_key = s3_info.get("object", {}).get("key", "")
        key = urllib.parse.unquote_plus(raw_key)

        logger.info("report-mailer triggered: trigger=s3 bucket=%s key=%s", bucket, key)
        logger.info("report-mailer triggered", extra={"trigger": "s3", "key": key, "bucket": bucket})

        response = s3_client.get_object(Bucket=bucket, Key=key)
        csv_bytes = response["Body"].read()

        filename = key.split("/")[-1]
        week = filename.removesuffix(".csv")

        msg = EmailMessage()
        msg["Subject"] = f"Weekly Meetings Report - {week}"
        msg["From"] = f"Meetings Reports <{sender}>"
        msg["To"] = recipient
        msg.set_content(
            f"Hello,\n\nPlease find attached the weekly meetings report for {week}.\n\nBest regards,\nMeetings App"
        )
        msg.add_attachment(
            csv_bytes,
            maintype="text",
            subtype="csv",
            filename=filename,
        )

        ses_client.send_email(
            FromEmailAddress=sender,
            Destination={"ToAddresses": [recipient]},
            Content={"Raw": {"Data": msg.as_bytes()}},
        )
        logger.info("report-mailer completed: emailed %s to %s", filename, recipient)

    return {"status": "success", "count": len(records)}

lambda_handler = handler
EOF
    filename = "index.py"
  }
}

# 13. Report Mailer Function
resource "aws_lambda_function" "report_mailer" {
  function_name    = "${var.project_name}-report-mailer"
  runtime          = "python3.12"
  handler          = "index.handler"
  role             = aws_iam_role.report_mailer_role.arn
  timeout          = 60
  memory_size      = 256
  filename         = data.archive_file.report_mailer_zip.output_path
  source_code_hash = data.archive_file.report_mailer_zip.output_base64sha256

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.report_mailer.name
  }

  environment {
    variables = {
      SENDER_EMAIL    = var.sender_email
      RECIPIENT_EMAIL = var.recipient_email
    }
  }

  tags = {
    PROJECT_NAME = var.project_name
  }

  depends_on = [
    aws_cloudwatch_log_group.report_mailer,
    aws_iam_role_policy_attachment.report_mailer_basic,
  ]

  lifecycle {
    ignore_changes = [source_code_hash, tags, tags_all]
  }
}

# 14. Decoupled Lambda Permission (Dynamically references S3 Bucket ARN)
resource "aws_lambda_permission" "report_mailer_s3" {
  statement_id   = "AllowExecutionFromS3Bucket"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.report_mailer.function_name
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.reports.arn
  source_account = data.aws_caller_identity.current.account_id

  lifecycle {
    ignore_changes = [statement_id]
  }
}

# S3 Bucket Notification (Depends on Permission, preventing race condition)
resource "aws_s3_bucket_notification" "reports_notification" {
  bucket     = aws_s3_bucket.reports.id
  depends_on = [aws_lambda_permission.report_mailer_s3]

  lambda_function {
    lambda_function_arn = aws_lambda_function.report_mailer.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "reports/"
    filter_suffix       = ".csv"
  }
}

# ==============================================================================
# SES Email Identity
# ==============================================================================

# 15. SES Recipient Email Identity
resource "aws_ses_email_identity" "recipient" {
  email = var.recipient_email
}
