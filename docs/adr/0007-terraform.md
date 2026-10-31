# 0007. The Cloud as Code: From CloudFormation to Terraform

Date: 2026-10-31

## Status

Accepted

## Context

In Labs 4, 5, and 6, our project infrastructure grew incrementally using AWS CloudFormation templates:
- `infra/auth.yaml`: Amazon Cognito User Pool, Hosted UI domain, Google Identity Provider, and Managed Login v2 branding.
- `infra/reports.yaml`: S3 reports bucket, SQS request queue, EventBridge Scheduler, report-builder Lambda (VPC), and report-mailer Lambda.
- `infra/ai.yaml`: Agenda parser Lambda (Bedrock Claude Haiku 4.5), Lambda Function URL with CORS, CloudWatch Log Group, and AWS Budgets alarm.

While CloudFormation successfully deployed these resources, it presented several critical operational and architectural limitations as our project matured:
1. **Single-Cloud Boundary**: CloudFormation cannot manage resources outside AWS, such as our Google Cloud OAuth client credentials, GitHub branch protection, or multi-cloud assets.
2. **State & Environment Coupling**: CloudFormation binds state management entirely inside individual AWS accounts, making multi-environment management (dev, stage, prod, white-label) cumbersome and dependent on complex parameter overrides or StackSets.
3. **Circular Dependencies**: Certain resource combinations (e.g. S3 bucket notifications triggering Lambdas that require bucket permissions) caused circular dependency deadlocks in CloudFormation that required manual template workarounds.
4. **Governance & Secrets**: Managing sensitive parameters (such as the Google Client Secret) required careful parameter passing with NoEcho or external parameter stores, with stack updates initiated from local developer machines.

## Decision

We migrate our infrastructure definition from AWS CloudFormation to **Terraform** managed via **HCP Terraform (formerly Terraform Cloud)** using dynamic AWS OIDC credentials:

1. **Declarative HCL Modules**:
   - Replaced `infra/auth.yaml`, `infra/reports.yaml`, and `infra/ai.yaml` with clean, modular Terraform files in `infra/`: `auth.tf`, `reports.tf`, `ai.tf`, `versions.tf`, `variables.tf`, and `outputs.tf`.
   - Preserved all 16 output contracts in `infra/outputs.tf` to maintain seamless compatibility with application deployment scripts and environment variables.
   - Decoupled circular dependencies natively using separate resources: `aws_s3_bucket`, `aws_lambda_permission`, and `aws_s3_bucket_notification`.

2. **State Management & Central Locking via HCP Terraform**:
   - Remote state is stored and locked in HCP Terraform under organization `ooad-MaksIMMum` and workspace `new-project-dev`.
   - Local state files (`terraform.tfstate`) are eliminated from laptops and git repositories, preventing concurrent execution corruption and state drift.

3. **Dynamic AWS Credentials via IAM OIDC**:
   - Eliminated static AWS access keys for CI/CD and infrastructure changes.
   - Deployed a bootstrap IAM OIDC Provider (`https://app.terraform.io`) and execution role (`hcp-terraform-ooad-MaksIMMum`).
   - HCP Terraform exchanges short-lived OIDC tokens for temporary AWS session credentials scoped strictly to our organization and workspace run phase.

4. **Non-Destructive Zero-Downtime Resource Adoption**:
   - Applied `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain` across existing CloudFormation stacks before releasing stack ownership.
   - Adopted all 27 live AWS assets (including 8 existing Cognito users and 4 historical S3 reports) using declarative `import { ... }` blocks in `infra/imports.tf`, verifying plan convergence with zero recreation (`# forces replacement`) of stateful resources.

## Alternatives Considered

1. **Retain CloudFormation**:
   - *Pros*: Native AWS service, zero state storage costs, automatic rollback on stack failure.
   - *Cons*: Strictly restricted to AWS; YAML/JSON lacks modular abstractions, functions, and dynamic provider ecosystems; hard to manage multi-cloud resources or third-party SaaS integrations.
2. **AWS CDK (Cloud Development Kit)**:
   - *Pros*: Expressive programming languages (TypeScript/Python), higher-level L2/L3 constructs.
   - *Cons*: Still compiles down to CloudFormation templates under the hood, inheriting all CloudFormation runtime constraints, rollback delays, and AWS-only boundaries.
3. **OpenTofu**:
   - *Pros*: Fully open-source MPL-2.0 fork of Terraform with compatible HCL syntax.
   - *Cons*: While functionally compatible with our HCL code, HCP Terraform provides turnkey managed remote state locking, speculative PR plan checks, and managed OIDC integrations on its free tier. Our HCL is authored to remain fully compatible with OpenTofu should we choose to self-host state in S3.

## Consequences

### Positive
- **Multi-Provider Unification**: One tool and workflow can orchestrate AWS, Google Cloud OAuth, GitHub, and DNS in unified plans.
- **Previewable & Auditable Changes**: Every infrastructure change is planned in GitHub pull requests (`+ to add, ~ to update, - to destroy`) before applying.
- **Zero Static Secrets**: HCP Terraform uses short-lived OIDC tokens. Sensitive variables (Google Client Secret) are marked `sensitive = true`, preventing plaintext exposure in logs and CLI outputs.
- **Native Dependency Graph**: Terraform resolves dependencies from resource references automatically, eliminating manual `DependsOn` ordering hacks.

### Negative & Mitigations
- **Manual State Ownership**: Unlike CloudFormation where AWS manages the state implicitly, Terraform relies on a state file.
  - *Mitigation*: State is centralized and encrypted in HCP Terraform with automated backups and locking.
- **No Automatic Rollback on Failure**: If an apply fails midway, Terraform pauses where it stopped rather than rolling back.
  - *Mitigation*: The team reviews plans carefully in PR checks before merging. Failed steps are resolved idempotently by fixing the HCL and re-applying.
- **HCP Terraform Outage Contingency**:
  - *Mitigation*: The state can be exported via `terraform state pull`. If HCP Terraform experiences downtime, teams can break-glass switch to a local or S3 backend with temporary AWS credentials.
