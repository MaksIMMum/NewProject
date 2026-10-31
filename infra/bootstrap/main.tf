data "aws_caller_identity" "current" {}

# Fetch the live TLS certificate chain of HCP Terraform
data "tls_certificate" "tfc_certificate" {
  url = "https://${var.tfc_hostname}"
}

# 1. AWS IAM OpenID Connect Provider for HCP Terraform
resource "aws_iam_openid_connect_provider" "tfc_provider" {
  url            = "https://${var.tfc_hostname}"
  client_id_list = [var.tfc_audience]
  thumbprint_list = distinct(compact([
    data.tls_certificate.tfc_certificate.certificates[0].sha1_fingerprint,
    "06b25927c42a721631c1efd9431e648fa62e1e39", # Starfield Services Root CA - G2 (chain root)
    "9e99a48a9960b14926cc7f3b02e22da2b0ab7280"  # DigiCert Global Root CA (HashiCorp well-known)
  ]))

  tags = {
    Name         = "HCP-Terraform-OIDC"
    PROJECT_NAME = var.project_name
  }
}

# 2. IAM Role for HCP Terraform Execution with Dynamic Scoped Trust Policy
resource "aws_iam_role" "tfc_role" {
  name        = var.role_name
  description = "IAM Role assumed by HCP Terraform runs in organization ${var.tfc_organization} via Dynamic AWS OIDC"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "HCPTerraformOIDCAuth"
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.tfc_provider.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "${var.tfc_hostname}:aud" = var.tfc_audience
          }
          StringLike = {
            "${var.tfc_hostname}:sub" = var.tfc_subject_pattern
          }
        }
      }
    ]
  })

  tags = {
    PROJECT_NAME = var.project_name
  }
}

# 3. Attach AdministratorAccess for Complete Infrastructure Provisioning
resource "aws_iam_role_policy_attachment" "tfc_admin" {
  role       = aws_iam_role.tfc_role.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
