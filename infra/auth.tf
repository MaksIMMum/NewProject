# =============================================================================
# Amazon Cognito User Pool (Stateful Core Registry - 8 Existing Users)
# =============================================================================

resource "aws_cognito_user_pool" "users" {
  name = "${var.project_name}-users"

  user_pool_tier = "ESSENTIALS"

  admin_create_user_config {
    allow_admin_create_user_only = false
  }

  # Users sign in with their email address; Cognito emails a code to verify it.
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  # Profile updates to email require entering a verification code before applying.
  user_attribute_update_settings {
    attributes_require_verification_before_update = ["email"]
  }

  username_configuration {
    case_sensitive = false
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true
  }

  schema {
    name                = "name"
    attribute_data_type = "String"
    required            = false
    mutable             = true
  }

  # Mirrored by the frontend signup form
  password_policy {
    minimum_length    = 8
    require_lowercase = true
    require_numbers   = true
    require_uppercase = false
    require_symbols   = false
  }

  mfa_configuration = "OFF"

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
    email_subject        = "Your Meetings verification code"
    email_message        = "Your Meetings verification code is {####}"
  }

  tags = {
    PROJECT_NAME = var.project_name
  }

  # CRITICAL: Prevent accidental destruction of live user accounts
  lifecycle {
    prevent_destroy = true
    ignore_changes  = [schema, tags, tags_all]
  }
}

# =============================================================================
# Cognito Hosted UI Domain (Managed Login v2)
# =============================================================================

resource "aws_cognito_user_pool_domain" "main" {
  domain                = "${var.project_name}-${data.aws_caller_identity.current.account_id}"
  user_pool_id          = aws_cognito_user_pool.users.id
  managed_login_version = 2
}

# =============================================================================
# Optional Google Identity Provider
# =============================================================================

resource "aws_cognito_identity_provider" "google" {
  count = var.google_client_id != "" ? 1 : 0

  user_pool_id  = aws_cognito_user_pool.users.id
  provider_name = "Google"
  provider_type = "Google"

  provider_details = {
    client_id        = var.google_client_id
    client_secret    = var.google_client_secret
    authorize_scopes = "openid email profile"
  }

  attribute_mapping = {
    email          = "email"
    email_verified = "email_verified"
    name           = "name"
    username       = "sub"
  }

  lifecycle {
    ignore_changes = [
      provider_details["attributes_url"],
      provider_details["attributes_url_add_attributes"],
      provider_details["authorize_url"],
      provider_details["oidc_issuer"],
      provider_details["token_request_method"],
      provider_details["token_url"],
    ]
  }
}

# =============================================================================
# Public Web SPA App Client (No Secret, SRP Auth)
# =============================================================================

resource "aws_cognito_user_pool_client" "web" {
  name         = "${var.project_name}-web"
  user_pool_id = aws_cognito_user_pool.users.id

  generate_secret = false

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH"
  ]

  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  supported_identity_providers = var.google_client_id != "" ? ["COGNITO", "Google"] : ["COGNITO"]

  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]

  callback_urls = concat(var.app_urls, [for u in var.app_urls : "${u}/login"])
  logout_urls   = concat(var.app_urls, [for u in var.app_urls : "${u}/login"])

  depends_on = [
    aws_cognito_identity_provider.google
  ]

  lifecycle {
    ignore_changes = [generate_secret]
  }
}

# =============================================================================
# Managed Login v2 Branding
# =============================================================================

resource "aws_cognito_managed_login_branding" "branding" {
  user_pool_id                = aws_cognito_user_pool.users.id
  client_id                   = aws_cognito_user_pool_client.web.id
  use_cognito_provided_values = true

  depends_on = [
    aws_cognito_user_pool_domain.main
  ]
}
