# Infrastructure Bootstrap: AWS IAM OIDC Provider & HCP Execution Role

This standalone Terraform module configures AWS to trust HCP Terraform (`app.terraform.io`) via OpenID Connect (OIDC). It provisions the IAM OIDC Provider and the `hcp-terraform-ooad-MaksIMMum` IAM execution role with dynamic credential assume-role policies and `AdministratorAccess`.

## Architecture Overview

- **OIDC Provider**: `https://app.terraform.io` with audience `aws.workload.identity`
- **Execution Role**: `hcp-terraform-ooad-MaksIMMum`
- **Trust Policy**: Scoped via `sts:AssumeRoleWithWebIdentity` to `app.terraform.io:aud == "aws.workload.identity"` and `app.terraform.io:sub` matching `organization:ooad-MaksIMMum:*`
- **Permissions**: `AdministratorAccess` (`arn:aws:iam::aws:policy/AdministratorAccess`)
- **State Storage**: Isolated local state (`terraform.tfstate`), never pushed to remote backend (chicken-and-egg prevention).

## Prerequisites

- Terraform >= 1.5.0
- AWS CLI with credentials for AWS Account 277206319329 in `us-east-1`
- Environment variables configured via `.env` (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`)

## Execution Guide

Run this module **locally once** using administrator credentials:

```bash
cd infra/bootstrap
terraform init
terraform plan
terraform apply
```

## Outputs & HCP Workspace Configuration

After running `terraform apply`, query the generated outputs:

```bash
terraform output -raw role_arn
terraform output -raw oidc_provider_arn
```

Configure the following environment variables in the HCP Terraform workspace `new-project-dev`:
- `TFC_AWS_PROVIDER_AUTH`: `true` (Environment)
- `TFC_AWS_RUN_ROLE_ARN`: Value of `role_arn` (Environment)
- `AWS_REGION`: `us-east-1` (Environment)
