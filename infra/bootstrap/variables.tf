variable "aws_region" {
  type        = string
  description = "AWS region for provisioning bootstrap resources"
  default     = "us-east-1"
}

variable "project_name" {
  type        = string
  description = "Project identifier tag"
  default     = "new-project"
}

variable "tfc_organization" {
  type        = string
  description = "HCP Terraform Organization name"
  default     = "ooad-MaksIMMum"
}

variable "role_name" {
  type        = string
  description = "IAM role name assumed by HCP Terraform runs"
  default     = "hcp-terraform-ooad-MaksIMMum"
}

variable "tfc_hostname" {
  type        = string
  description = "Hostname of HCP Terraform / Terraform Enterprise"
  default     = "app.terraform.io"
}

variable "tfc_audience" {
  type        = string
  description = "Audience claim expected in HCP Terraform workload identity tokens"
  default     = "aws.workload.identity"
}

variable "tfc_subject_pattern" {
  type        = string
  description = "Subject (sub) claim pattern for OIDC trust policy condition"
  default     = "organization:ooad-MaksIMMum:*"
}
