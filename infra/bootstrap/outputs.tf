output "oidc_provider_arn" {
  description = "ARN of the IAM OpenID Connect Provider for HCP Terraform"
  value       = aws_iam_openid_connect_provider.tfc_provider.arn
}

output "oidc_provider_url" {
  description = "URL of the IAM OpenID Connect Provider"
  value       = aws_iam_openid_connect_provider.tfc_provider.url
}

output "role_arn" {
  description = "ARN of the IAM Role assumed by HCP Terraform runs (set as TFC_AWS_RUN_ROLE_ARN)"
  value       = aws_iam_role.tfc_role.arn
}

output "role_name" {
  description = "Name of the IAM Role assumed by HCP Terraform runs"
  value       = aws_iam_role.tfc_role.name
}

output "hcp_workspace_env_vars" {
  description = "Required environment variables to set on the HCP Terraform workspace"
  value = {
    TFC_AWS_PROVIDER_AUTH = "true"
    TFC_AWS_RUN_ROLE_ARN  = aws_iam_role.tfc_role.arn
    AWS_REGION            = var.aws_region
  }
}

output "hcp_terraform_setup_instructions" {
  description = "Instructions for configuring the HCP Terraform Workspace"
  value       = <<-EOT
    ========================================================================
    HCP TERRAFORM WORKSPACE CONFIGURATION INSTRUCTIONS
    ========================================================================
    1. Navigate to: https://app.terraform.io/app/${var.tfc_organization}/workspaces
    2. Open or create workspace: 'new-project-dev'
    3. Under Settings -> General:
       - Execution Mode: Remote
       - Working Directory: infra
    4. Under Settings -> Version Control:
       - Connect to GitHub repo: MaksIMMum/NewProject
       - Branch: main
       - Include Trigger Prefixes: infra/
    5. Under Variables (Environment Variables):
       - TFC_AWS_PROVIDER_AUTH = true (Category: Environment, Sensitive: false)
       - TFC_AWS_RUN_ROLE_ARN  = ${aws_iam_role.tfc_role.arn} (Category: Environment, Sensitive: false)
       - AWS_REGION            = ${var.aws_region} (Category: Environment, Sensitive: false)
    ========================================================================
  EOT
}
