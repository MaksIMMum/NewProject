# ==============================================================================
# AI Agenda Parser Stack (Milestone 2 - infra/ai.tf)
# Runs outside the VPC with direct internet egress to Amazon Bedrock and Cognito.
# ==============================================================================

# 1. CloudWatch Log Group
resource "aws_cloudwatch_log_group" "agenda_parser" {
  name              = "/aws/lambda/${var.project_name}-agenda-parser"
  retention_in_days = 7

  tags = {
    PROJECT_NAME = var.project_name
  }
}

# 2. IAM Execution Role & Policies
resource "aws_iam_role" "agenda_parser_role" {
  name = "${var.project_name}-agenda-parser-role"

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

resource "aws_iam_role_policy_attachment" "agenda_parser_basic" {
  role       = aws_iam_role.agenda_parser_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "agenda_parser_bedrock" {
  name = "BedrockInference"
  role = aws_iam_role.agenda_parser_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "bedrock-mantle:CreateInference",
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Effect   = "Allow"
        Resource = "*"
      }
    ]
  })
}

# 3. Agenda Parser Lambda Function (Container, No VPC)
resource "aws_lambda_function" "agenda_parser" {
  function_name = "${var.project_name}-agenda-parser"
  package_type  = "Image"
  image_uri     = var.image_uri
  role          = aws_iam_role.agenda_parser_role.arn
  timeout       = 30
  memory_size   = 512

  image_config {
    command = ["app.ai.agenda_lambda.handler"]
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.agenda_parser.name
  }

  environment {
    variables = {
      COGNITO_USER_POOL_ID = var.cognito_user_pool_id != "" ? var.cognito_user_pool_id : aws_cognito_user_pool.users.id
      COGNITO_CLIENT_ID    = var.cognito_client_id != "" ? var.cognito_client_id : aws_cognito_user_pool_client.web.id
      PARSER_MODEL         = var.parser_model
      PROMPT_VERSION       = "agenda-v1"
      AWS_LWA_ENABLE       = "false"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.agenda_parser,
    aws_iam_role_policy_attachment.agenda_parser_basic,
  ]

  tags = {
    PROJECT_NAME = var.project_name
  }
}

# 4. Lambda Function URL
resource "aws_lambda_function_url" "agenda_parser_url" {
  function_name      = aws_lambda_function.agenda_parser.function_name
  authorization_type = "NONE"

  cors {
    allow_credentials = false
    allow_origins     = split(",", var.allowed_origins)
    allow_methods     = ["POST"]
    allow_headers     = ["authorization", "content-type"]
    max_age           = 86400
  }
}

# 5. Permission: Invoke Function URL
resource "aws_lambda_permission" "agenda_parser_url_permission" {
  statement_id           = "${var.project_name}-ai-AgendaParserUrlPermission"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.agenda_parser.function_name
  principal              = "*"
  function_url_auth_type = "NONE"

  lifecycle {
    ignore_changes = [statement_id]
  }
}

# 6. Permission: Invoke Function
resource "aws_lambda_permission" "agenda_parser_invoke_permission" {
  statement_id  = "${var.project_name}-ai-AgendaParserInvokePermission"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.agenda_parser.function_name
  principal     = "*"

  lifecycle {
    ignore_changes = [statement_id, invoked_via_function_url]
  }
}

# 7. AWS Monthly Cost Budget Alarm ($5.00 USD)
resource "aws_budgets_budget" "monthly_budget" {
  name         = "${var.project_name}-ai-monthly-budget"
  budget_type  = "COST"
  limit_amount = "5.0"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
}
