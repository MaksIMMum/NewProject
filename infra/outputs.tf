# =============================================================================
# Auth Outputs (auth.yaml contract - 6 outputs)
# =============================================================================

output "UserPoolId" {
  description = "Cognito User Pool ID"
  value       = aws_cognito_user_pool.users.id
}

output "UserPoolClientId" {
  description = "Cognito User Pool App Client ID"
  value       = aws_cognito_user_pool_client.web.id
}

output "Domain" {
  description = "Cognito domain for OAuth redirects (Google Hosted UI)"
  value       = "${aws_cognito_user_pool_domain.main.domain}.auth.${var.aws_region}.amazoncognito.com"
}

output "Issuer" {
  description = "Issuer URL of the Cognito tokens; used by backend JWT verifiers"
  value       = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.users.id}"
}

output "GoogleEnabled" {
  description = "Flag indicating whether Google IdP is configured (string 'true' or 'false')"
  value       = var.google_client_id != "" ? "true" : "false"
}

output "Region" {
  description = "AWS region for the deployed infrastructure"
  value       = var.aws_region
}

# =============================================================================
# Reports Outputs (reports.yaml contract - 6 outputs)
# =============================================================================

output "ReportsBucketName" {
  description = "Name of the private reports S3 bucket"
  value       = aws_s3_bucket.reports.id
}

output "ReportRequestsQueueUrl" {
  description = "URL of the SQS queue for report generation requests"
  value       = aws_sqs_queue.report_requests.url
}

output "ReportRequestsQueueArn" {
  description = "ARN of the SQS queue for report generation requests"
  value       = aws_sqs_queue.report_requests.arn
}

output "ReportRequestsDLQUrl" {
  description = "URL of the Dead-Letter Queue"
  value       = aws_sqs_queue.report_requests_dlq.url
}

output "ReportBuilderFunctionName" {
  description = "Name of the VPC report-builder Lambda function"
  value       = aws_lambda_function.report_builder.function_name
}

output "ReportMailerFunctionName" {
  description = "Name of the report-mailer Lambda function"
  value       = aws_lambda_function.report_mailer.function_name
}

# =============================================================================
# AI Subsystem Outputs (ai.yaml contract - 4 outputs)
# =============================================================================

output "AiFunctionUrl" {
  description = "Function URL of the AI agenda parser"
  value       = aws_lambda_function_url.agenda_parser_url.function_url
}

output "AiUrl" {
  description = "Function URL without trailing slash (consumed by frontend and deploy-ai.sh)"
  value       = trimsuffix(aws_lambda_function_url.agenda_parser_url.function_url, "/")
}

output "AgendaParserFunctionName" {
  description = "Name of the AI agenda parser Lambda function"
  value       = aws_lambda_function.agenda_parser.function_name
}

output "AgendaParserLogGroup" {
  description = "Name of the CloudWatch Log Group for AI agenda parser"
  value       = aws_cloudwatch_log_group.agenda_parser.name
}
