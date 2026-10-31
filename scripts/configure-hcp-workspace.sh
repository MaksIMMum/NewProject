#!/usr/bin/env bash
# ==============================================================================
# configure-hcp-workspace.sh
#
# Configures the HCP Terraform workspace 'new-project-dev' in organization
# 'ooad-MaksIMMum' with remote execution mode, VCS connection to
# MaksIMMum/NewProject (working-directory: infra/), and Dynamic AWS OIDC
# environment variables.
# ==============================================================================
set -euo pipefail

ORG_NAME="${TFC_ORG:-ooad-MaksIMMum}"
WORKSPACE_NAME="${TFC_WORKSPACE:-new-project-dev}"
REPO_ID="${TFC_REPO_ID:-MaksIMMum/NewProject}"
BRANCH="${TFC_BRANCH:-main}"
ROLE_ARN="${1:-arn:aws:iam::277206319329:role/hcp-terraform-ooad-MaksIMMum}"
AWS_DEFAULT_REGION="${AWS_REGION:-us-east-1}"
TFC_TOKEN="${TFC_TOKEN:-${TF_TOKEN_app_terraform_io:-}}"

# Resolve HCP API Token
if [ -z "$TFC_TOKEN" ]; then
  CRED_FILE="$HOME/.terraform.d/credentials.tfrc.json"
  if [ -f "$CRED_FILE" ]; then
    TFC_TOKEN="$(jq -r '.credentials["app.terraform.io"].token // empty' "$CRED_FILE" 2>/dev/null || true)"
  fi
fi

if [ -z "$TFC_TOKEN" ]; then
  echo "Error: HCP Terraform token required. Set TFC_TOKEN or TF_TOKEN_app_terraform_io," >&2
  echo "or configure credentials in ~/.terraform.d/credentials.tfrc.json via 'terraform login'." >&2
  exit 1
fi

API_URL="https://app.terraform.io/api/v2"
AUTH_HEADER="Authorization: Bearer $TFC_TOKEN"
CONTENT_HEADER="Content-Type: application/vnd.api+json"

echo "==> [HCP] Inspecting workspace '$WORKSPACE_NAME' in organization '$ORG_NAME'..."

WS_RES="$(curl -s -H "$AUTH_HEADER" -H "$CONTENT_HEADER" "$API_URL/organizations/$ORG_NAME/workspaces/$WORKSPACE_NAME" || true)"
WS_ID="$(echo "$WS_RES" | jq -r '.data.id // empty')"

VCS_OAUTH_TOKEN_ID="${TFC_OAUTH_TOKEN_ID:-}"
if [ -z "$VCS_OAUTH_TOKEN_ID" ]; then
  # Look up existing VCS OAuth client in organization if available
  OAUTH_TOKENS_RES="$(curl -s -H "$AUTH_HEADER" "$API_URL/organizations/$ORG_NAME/oauth-clients" || true)"
  VCS_OAUTH_TOKEN_ID="$(echo "$OAUTH_TOKENS_RES" | jq -r '.data[0].relationships["oauth-tokens"].data[0].id // empty')"
fi

if [ -z "$WS_ID" ]; then
  echo "==> [HCP] Workspace not found. Creating '$WORKSPACE_NAME'..."
  if [ -n "$VCS_OAUTH_TOKEN_ID" ]; then
    CREATE_PAYLOAD=$(cat <<EOF
{
  "data": {
    "type": "workspaces",
    "attributes": {
      "name": "$WORKSPACE_NAME",
      "execution-mode": "remote",
      "working-directory": "infra",
      "auto-apply": false,
      "file-triggers-enabled": true,
      "trigger-prefixes": ["infra/"],
      "vcs-repo": {
        "identifier": "$REPO_ID",
        "branch": "$BRANCH",
        "oauth-token-id": "$VCS_OAUTH_TOKEN_ID"
      }
    }
  }
}
EOF
)
  else
    CREATE_PAYLOAD=$(cat <<EOF
{
  "data": {
    "type": "workspaces",
    "attributes": {
      "name": "$WORKSPACE_NAME",
      "execution-mode": "remote",
      "working-directory": "infra",
      "auto-apply": false,
      "file-triggers-enabled": true,
      "trigger-prefixes": ["infra/"]
    }
  }
}
EOF
)
  fi

  CREATE_RES="$(curl -s -X POST -H "$AUTH_HEADER" -H "$CONTENT_HEADER" -d "$CREATE_PAYLOAD" "$API_URL/organizations/$ORG_NAME/workspaces")"
  WS_ID="$(echo "$CREATE_RES" | jq -r '.data.id // empty')"
  if [ -z "$WS_ID" ]; then
    echo "Error: Failed to create workspace: $CREATE_RES" >&2
    exit 1
  fi
  echo "==> [HCP] Created workspace ID: $WS_ID"
else
  echo "==> [HCP] Workspace exists (ID: $WS_ID). Updating settings..."
  if [ -n "$VCS_OAUTH_TOKEN_ID" ]; then
    UPDATE_PAYLOAD=$(cat <<EOF
{
  "data": {
    "type": "workspaces",
    "attributes": {
      "execution-mode": "remote",
      "working-directory": "infra",
      "auto-apply": false,
      "file-triggers-enabled": true,
      "trigger-prefixes": ["infra/"],
      "vcs-repo": {
        "identifier": "$REPO_ID",
        "branch": "$BRANCH",
        "oauth-token-id": "$VCS_OAUTH_TOKEN_ID"
      }
    }
  }
}
EOF
)
  else
    UPDATE_PAYLOAD=$(cat <<EOF
{
  "data": {
    "type": "workspaces",
    "attributes": {
      "execution-mode": "remote",
      "working-directory": "infra",
      "auto-apply": false,
      "file-triggers-enabled": true,
      "trigger-prefixes": ["infra/"]
    }
  }
}
EOF
)
  fi
  curl -s -X PATCH -H "$AUTH_HEADER" -H "$CONTENT_HEADER" -d "$UPDATE_PAYLOAD" "$API_URL/workspaces/$WS_ID" >/dev/null
  echo "==> [HCP] Workspace settings updated."
fi

# Helper to create or update variables
set_workspace_var() {
  local key="$1"
  local val="$2"
  local category="$3"
  local sensitive="$4"
  local description="$5"

  echo "  -> Setting $category variable: $key (sensitive: $sensitive)..."
  local existing_var_id
  existing_var_id="$(curl -s -H "$AUTH_HEADER" "$API_URL/workspaces/$WS_ID/vars" | \
    jq -r --arg k "$key" '.data[] | select(.attributes.key == $k) | .id' | head -n1)"

  local payload
  payload=$(cat <<EOF
{
  "data": {
    "type": "vars",
    "attributes": {
      "key": "$key",
      "value": "$val",
      "category": "$category",
      "hcl": false,
      "sensitive": $sensitive,
      "description": "$description"
    }
  }
}
EOF
)

  if [ -n "$existing_var_id" ]; then
    curl -s -X PATCH -H "$AUTH_HEADER" -H "$CONTENT_HEADER" -d "$payload" "$API_URL/workspaces/$WS_ID/vars/$existing_var_id" >/dev/null
  else
    curl -s -X POST -H "$AUTH_HEADER" -H "$CONTENT_HEADER" -d "$payload" "$API_URL/workspaces/$WS_ID/vars" >/dev/null
  fi
}

echo "==> [HCP] Configuring Workspace Variables..."

# 1. Dynamic AWS OIDC Environment Variables
set_workspace_var "TFC_AWS_PROVIDER_AUTH" "true" "env" false "Enables dynamic AWS workload identity authentication via OIDC"
set_workspace_var "TFC_AWS_RUN_ROLE_ARN" "$ROLE_ARN" "env" false "AWS IAM Role ARN assumed by HCP Terraform runs"
set_workspace_var "AWS_REGION" "$AWS_DEFAULT_REGION" "env" false "Default AWS target region"
set_workspace_var "TFC_AWS_WORKLOAD_IDENTITY_AUDIENCE" "aws.workload.identity" "env" false "Target audience claim for AWS STS token exchange"

# 2. Terraform Input Variables
set_workspace_var "project_name" "new-project" "terraform" false "Resource naming and tagging prefix"
set_workspace_var "aws_region" "$AWS_DEFAULT_REGION" "terraform" false "AWS region for Terraform resources"
set_workspace_var "recipient_email" "kornatskyy.pn@ucu.edu.ua" "terraform" false "Recipient email address for weekly reports"
set_workspace_var "sender_email" "kornatskyy.pn@ucu.edu.ua" "terraform" false "Verified sender email identity in SES"
set_workspace_var "alert_email" "kornatskyy.pn@ucu.edu.ua" "terraform" false "Notification email for AWS Budgets alarm"

# 3. Sensitive Project Variables (Google OAuth)
if [ -n "${GOOGLE_CLIENT_SECRET:-}" ]; then
  set_workspace_var "google_client_id" "${GOOGLE_CLIENT_ID:-}" "terraform" false "Google OAuth Client ID"
  set_workspace_var "google_client_secret" "$GOOGLE_CLIENT_SECRET" "terraform" true "Google OAuth Client Secret (Sensitive)"
elif [ -n "${GOOGLE_CLIENT_ID:-}" ]; then
  set_workspace_var "google_client_id" "$GOOGLE_CLIENT_ID" "terraform" false "Google OAuth Client ID"
fi

echo "==> [HCP] Workspace '$WORKSPACE_NAME' configured successfully with Dynamic AWS OIDC!"
