# -----------------------------------------------------------------------------
# Core & Common Variables
# -----------------------------------------------------------------------------

variable "project_name" {
  type        = string
  description = "Project identifier tag used in resource names and default tags"
  default     = "new-project"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*$", var.project_name))
    error_message = "project_name must start with a lowercase letter and contain only lowercase letters, digits, and hyphens."
  }
}

variable "aws_region" {
  type        = string
  description = "AWS region for provisioning resources"
  default     = "us-east-1"
}

# -----------------------------------------------------------------------------
# Auth Subsystem Variables (auth.yaml)
# -----------------------------------------------------------------------------

variable "app_urls" {
  type        = list(string)
  description = "Frontend origins (no trailing slash). OAuth redirects back to origin and <origin>/login"
  default     = ["http://localhost:5173", "http://localhost:3000"]
}

variable "google_client_id" {
  type        = string
  description = "Google OAuth client id; leave empty to keep Google sign-in disabled"
  default     = ""
}

variable "google_client_secret" {
  type        = string
  description = "Google OAuth client secret; marked sensitive to prevent log leakage"
  default     = ""
  sensitive   = true
}

# -----------------------------------------------------------------------------
# Reports Subsystem Variables (reports.yaml)
# -----------------------------------------------------------------------------

variable "image_uri" {
  type        = string
  description = "Full backend Docker container image URI including tag from ECR"
  default     = ""
}

variable "vpc_id" {
  type        = string
  description = "VPC ID where Aurora and report-builder Lambda reside"
  default     = ""
}

variable "subnet_ids" {
  type        = list(string)
  description = "Private subnet IDs for report-builder Lambda"
  default     = []
}

variable "security_group_id" {
  type        = string
  description = "Security group ID allowing outbound database access from VPC Lambda"
  default     = ""
}

variable "route_table_id" {
  type        = string
  description = "Route table ID to attach the S3 Gateway VPC Endpoint to"
  default     = ""
}

variable "database_url" {
  type        = string
  description = "Async PostgreSQL / Aurora connection string; marked sensitive"
  default     = ""
  sensitive   = true
}

variable "recipient_email" {
  type        = string
  description = "Email address that receives weekly reports via SES"
  default     = "kornatskyy.pn@ucu.edu.ua"
}

variable "sender_email" {
  type        = string
  description = "Verified email address that sends weekly reports via SES"
  default     = "kornatskyy.pn@ucu.edu.ua"
}

# -----------------------------------------------------------------------------
# AI Subsystem Variables (ai.yaml)
# -----------------------------------------------------------------------------

variable "parser_model" {
  type        = string
  description = "Foundation model ID on Amazon Bedrock"
  default     = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "allowed_origins" {
  type        = string
  description = "Comma-separated CORS origins allowed to call the AI parser Function URL"
  default     = "*"
}

variable "alert_email" {
  type        = string
  description = "Email address for AWS Budgets monthly alarm ($5.00)"
  default     = "kornatskyy.pn@ucu.edu.ua"
}

variable "cognito_user_pool_id" {
  type        = string
  description = "Cognito User Pool ID for token verification (optional override)"
  default     = ""
}

variable "cognito_client_id" {
  type        = string
  description = "Cognito Client ID for token verification (optional override)"
  default     = ""
}
