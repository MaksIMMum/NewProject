#!/usr/bin/env bash
# Deploys the AI agenda parser infrastructure (Lambda outside VPC, Function URL, Budgets) to AWS.
set -euo pipefail

main() {
  cd "$(dirname "$0")/.."
  export PATH="${HOME}/.local/bin:${PATH}"
  source infra/common.sh

  AI_STACK="$PROJECT_NAME-ai"

  require_auth_stack
  if ! stack_exists "$ECR_STACK"; then
    echo "Stack $ECR_STACK not found; run make deploy-backend first." >&2
    exit 1
  fi

  echo "==> Deploying '$PROJECT_NAME' AI infrastructure to $AWS_REGION"

  # 1. Image preparation
  TAG="$(git rev-parse --short HEAD)"
  if [ -n "$(git status --porcelain -- backend)" ]; then
    TAG="$TAG-dirty-$(date +%Y%m%d%H%M%S)"
  fi

  repository="$(output "$ECR_STACK" RepositoryUri)"
  image="$repository:$TAG"

  echo "==> [1/2] Building and pushing $image"
  ARCH="${ARCH:-x86_64}"
  docker_platform="linux/amd64"
  [ "$ARCH" = "arm64" ] && docker_platform="linux/arm64"

  if aws ecr describe-images --repository-name "$PROJECT_NAME-backend" --image-ids "imageTag=$TAG" >/dev/null 2>&1; then
    echo "    Image tag $TAG already in ECR, skipping build"
  else
    docker build --platform "$docker_platform" --tag "$image" backend
    aws ecr get-login-password | docker login --username AWS --password-stdin "${repository%%/*}"
    docker push "$image"
  fi

  # 2. Gather auth configuration
  pool_id="$(output "$AUTH_STACK" UserPoolId)"
  client_id="$(output "$AUTH_STACK" UserPoolClientId)"
  parser_model="${PARSER_MODEL:-us.anthropic.claude-haiku-4-5-20251001-v1:0}"
  alert_email="${ALERT_EMAIL:-${RECIPIENT_EMAIL:-kornatskyy.pn@ucu.edu.ua}}"
  allowed_origins="${CORS_ORIGINS_AWS:-*}"
  if [ -z "$allowed_origins" ]; then
    allowed_origins="*"
  fi

  # 3. Deploy AI CloudFormation stack
  echo "==> [2/2] Deploying CloudFormation stack $AI_STACK"
  aws cloudformation deploy \
    --stack-name "$AI_STACK" \
    --template-file infra/ai.yaml \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides \
      "ProjectName=$PROJECT_NAME" \
      "ImageUri=$image" \
      "CognitoUserPoolId=$pool_id" \
      "CognitoClientId=$client_id" \
      "ParserModel=$parser_model" \
      "AllowedOrigins=$allowed_origins" \
      "AlertEmail=$alert_email" \
    --tags "PROJECT_NAME=$PROJECT_NAME"

  ai_url="$(output "$AI_STACK" AiUrl)"
  function_name="$(output "$AI_STACK" AgendaParserFunctionName)"

  echo ""
  echo "==> AI parser deployed successfully!"
  echo "    Function Name: $function_name"
  echo "    AI URL:        $ai_url"
  echo "    Model:         $parser_model"
  echo "    Budget Alarm:  \$5.00/month -> $alert_email"

  # Write VITE_AI_URL to .env for frontend build if present
  if [ -f .env ]; then
    if grep -q "^VITE_AI_URL=" .env; then
      sed -i "s|^VITE_AI_URL=.*|VITE_AI_URL=$ai_url|" .env
    else
      echo "VITE_AI_URL=$ai_url" >> .env
    fi
  fi
}

main "$@"
