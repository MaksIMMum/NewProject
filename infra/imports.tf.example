# ==============================================================================
# Declarative Resource Imports (Milestone 3 - Non-Destructive Resource Adoption)
# Maps live AWS resources to target Terraform resource addresses.
# Provider: hashicorp/aws ~> 6.0
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. Auth Subsystem (5 Primary Resources: Cognito User Pool, Domain, Client, IdP, Branding)
# ------------------------------------------------------------------------------

# Cognito User Pool (Stateful Core Registry - 8 Existing Users)
import {
  to = aws_cognito_user_pool.users
  id = "us-east-1_9U6SeBfDJ"
}

# Cognito Hosted UI Domain
import {
  to = aws_cognito_user_pool_domain.main
  id = "new-project-277206319329"
}

# Google Identity Provider (Conditional on google_client_id != "")
import {
  to = aws_cognito_identity_provider.google[0]
  id = "us-east-1_9U6SeBfDJ:Google"
}

# Public Web SPA App Client
import {
  to = aws_cognito_user_pool_client.web
  id = "us-east-1_9U6SeBfDJ/4toue9ji24bieqcdc9ibnns5gq"
}

# Managed Login v2 Branding
import {
  to = aws_cognito_managed_login_branding.branding
  id = "us-east-1_9U6SeBfDJ,0e070084-d8cb-4c74-9393-9b29e2e8a923"
}

# ------------------------------------------------------------------------------
# 2. Reports Subsystem (15 Primary Resources + 8 Decomposed Child Resources)
# ------------------------------------------------------------------------------

# Reports S3 Bucket (Stateful Historical Reports - 4 CSV Files)
import {
  to = aws_s3_bucket.reports
  id = "new-project-reports-277206319329"
}

# S3 Default Encryption Configuration
import {
  to = aws_s3_bucket_server_side_encryption_configuration.reports
  id = "new-project-reports-277206319329"
}

# S3 Lifecycle Configuration (90-Day Retention)
import {
  to = aws_s3_bucket_lifecycle_configuration.reports
  id = "new-project-reports-277206319329"
}

# S3 Gateway VPC Endpoint
import {
  to = aws_vpc_endpoint.s3
  id = "vpce-0dd00e2b58498ed6e"
}

# Report Requests Dead-Letter Queue (DLQ)
import {
  to = aws_sqs_queue.report_requests_dlq
  id = "https://sqs.us-east-1.amazonaws.com/277206319329/new-project-report-requests-dlq"
}

# Report Requests Main SQS Queue
import {
  to = aws_sqs_queue.report_requests
  id = "https://sqs.us-east-1.amazonaws.com/277206319329/new-project-report-requests"
}

# EventBridge Scheduler Execution IAM Role
import {
  to = aws_iam_role.scheduler_role
  id = "new-project-reports-SchedulerRole-EeBgFq5ywFcX"
}

# Scheduler Inline IAM Policy
import {
  to = aws_iam_role_policy.scheduler_policy
  id = "new-project-reports-SchedulerRole-EeBgFq5ywFcX:SendReportRequests"
}

# EventBridge Scheduler Schedule (Weekly Report Trigger)
import {
  to = aws_scheduler_schedule.weekly_report
  id = "default/new-project-weekly-report"
}

# CloudWatch Log Group for Report Builder Lambda
import {
  to = aws_cloudwatch_log_group.report_builder
  id = "/aws/lambda/new-project-report-builder"
}

# Report Builder Execution IAM Role
import {
  to = aws_iam_role.report_builder_role
  id = "new-project-reports-ReportBuilderRole-zd7cNHwknkzz"
}

# Report Builder VPC Managed Policy Attachment
import {
  to = aws_iam_role_policy_attachment.report_builder_vpc
  id = "new-project-reports-ReportBuilderRole-zd7cNHwknkzz/arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# Report Builder SQS Managed Policy Attachment
import {
  to = aws_iam_role_policy_attachment.report_builder_sqs
  id = "new-project-reports-ReportBuilderRole-zd7cNHwknkzz/arn:aws:iam::aws:policy/service-role/AWSLambdaSQSQueueExecutionRole"
}

# Report Builder S3 Writer Inline Policy
import {
  to = aws_iam_role_policy.report_builder_policy
  id = "new-project-reports-ReportBuilderRole-zd7cNHwknkzz:S3ReportWriter"
}

# Report Builder Lambda Function (VPC Container Image)
import {
  to = aws_lambda_function.report_builder
  id = "new-project-report-builder"
}

# Lambda SQS Event Source Mapping (Report Builder Queue Trigger)
import {
  to = aws_lambda_event_source_mapping.report_builder_sqs
  id = "7b05362d-dc6a-431a-80ca-17cece0832a0"
}

# CloudWatch Log Group for Report Mailer Lambda
import {
  to = aws_cloudwatch_log_group.report_mailer
  id = "/aws/lambda/new-project-report-mailer"
}

# Report Mailer Execution IAM Role
import {
  to = aws_iam_role.report_mailer_role
  id = "new-project-reports-ReportMailerRole-tU2KxX1imVNi"
}

# Report Mailer Basic Execution Managed Policy Attachment
import {
  to = aws_iam_role_policy_attachment.report_mailer_basic
  id = "new-project-reports-ReportMailerRole-tU2KxX1imVNi/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Report Mailer S3/SES Inline Policy
import {
  to = aws_iam_role_policy.report_mailer_policy
  id = "new-project-reports-ReportMailerRole-tU2KxX1imVNi:MailerPermissions"
}

# Report Mailer Lambda Function (Python 3.12 Inline Script)
import {
  to = aws_lambda_function.report_mailer
  id = "new-project-report-mailer"
}

# Lambda Permission: S3 Invocation for Report Mailer
import {
  to = aws_lambda_permission.report_mailer_s3
  id = "new-project-report-mailer/new-project-reports-MailerInvokePermission-Z0sntiDUguAc"
}

# S3 Bucket Notification (Reports to Mailer Lambda)
import {
  to = aws_s3_bucket_notification.reports_notification
  id = "new-project-reports-277206319329"
}

# SES Recipient Email Identity
import {
  to = aws_ses_email_identity.recipient
  id = "kornatskyy.pn@ucu.edu.ua"
}

# ------------------------------------------------------------------------------
# 3. AI Subsystem (7 Primary Resources + 2 Decomposed Child Resources)
# ------------------------------------------------------------------------------

# CloudWatch Log Group for Agenda Parser Lambda
import {
  to = aws_cloudwatch_log_group.agenda_parser
  id = "/aws/lambda/new-project-agenda-parser"
}

# Agenda Parser Execution IAM Role
import {
  to = aws_iam_role.agenda_parser_role
  id = "new-project-ai-AgendaParserRole-TIrLZQW75yXR"
}

# Agenda Parser Basic Execution Managed Policy Attachment
import {
  to = aws_iam_role_policy_attachment.agenda_parser_basic
  id = "new-project-ai-AgendaParserRole-TIrLZQW75yXR/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Agenda Parser Bedrock Inline Policy
import {
  to = aws_iam_role_policy.agenda_parser_bedrock
  id = "new-project-ai-AgendaParserRole-TIrLZQW75yXR:BedrockInference"
}

# Agenda Parser Lambda Function (Container Image, No VPC)
import {
  to = aws_lambda_function.agenda_parser
  id = "new-project-agenda-parser"
}

# Lambda Function URL (Public Endpoint with CORS)
import {
  to = aws_lambda_function_url.agenda_parser_url
  id = "new-project-agenda-parser"
}

# Lambda Permission: Public Function URL Invocation
import {
  to = aws_lambda_permission.agenda_parser_url_permission
  id = "new-project-agenda-parser/new-project-ai-AgendaParserUrlPermission-DlcI9wR3vS0z"
}

# Lambda Permission: Function Invocation via URL
import {
  to = aws_lambda_permission.agenda_parser_invoke_permission
  id = "new-project-agenda-parser/new-project-ai-AgendaParserInvokePermission-OLrezlXIZza1"
}

# AWS Monthly Cost Budget Alarm ($5.00 USD Limit)
import {
  to = aws_budgets_budget.monthly_budget
  id = "277206319329:new-project-ai-monthly-budget"
}
