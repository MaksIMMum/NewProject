#!/usr/bin/env bash
# Deploys the weekly reports pipeline (EventBridge, SQS, S3, Lambdas, SES) to AWS.
set -euo pipefail

main() {
  cd "$(dirname "$0")/.."
  source infra/common.sh

  REPORTS_STACK="$PROJECT_NAME-reports"
  PASSWORD_PARAM="/$PROJECT_NAME/db-password"

  require_auth_stack
  if ! stack_exists "$BACKEND_STACK"; then
    echo "Stack $BACKEND_STACK not found; run make deploy-backend first." >&2
    exit 1
  fi

  echo "==> Deploying '$PROJECT_NAME' reports infrastructure to $AWS_REGION"

  # 1. Image preparation
  TAG="$(git rev-parse --short HEAD)"
  if [ -n "$(git status --porcelain -- backend)" ]; then
    TAG="$TAG-dirty-$(date +%Y%m%d%H%M%S)"
  fi

  repository="$(output "$ECR_STACK" RepositoryUri)"
  image="$repository:$TAG"

  echo "==> [1/3] Building and pushing $image"
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

  # 2. Gather network and DB parameters from backend stack
  echo "==> [2/3] Gathering configuration from $BACKEND_STACK"
  db_password="$(aws ssm get-parameter --name "$PASSWORD_PARAM" --with-decryption \
    --query Parameter.Value --output text)"
  db_endpoint="$(output "$BACKEND_STACK" DatabaseEndpoint)"

  # Query VPC, subnets, SG and route table directly from AWS resources
  vpc_id="$(aws cloudformation describe-stack-resource --stack-name "$BACKEND_STACK" \
    --logical-resource-id Vpc --query "StackResourceDetail.PhysicalResourceId" --output text)"
  subnet_a="$(aws cloudformation describe-stack-resource --stack-name "$BACKEND_STACK" \
    --logical-resource-id PrivateSubnetA --query "StackResourceDetail.PhysicalResourceId" --output text)"
  subnet_b="$(aws cloudformation describe-stack-resource --stack-name "$BACKEND_STACK" \
    --logical-resource-id PrivateSubnetB --query "StackResourceDetail.PhysicalResourceId" --output text)"
  sec_group="$(aws cloudformation describe-stack-resource --stack-name "$BACKEND_STACK" \
    --logical-resource-id FunctionSecurityGroup --query "StackResourceDetail.PhysicalResourceId" --output text)"
  route_table="$(aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$vpc_id" \
    --query "RouteTables[0].RouteTableId" --output text)"

  db_url="postgresql+asyncpg://meetings:${db_password}@${db_endpoint}:5432/meetings"
  recipient_email="${RECIPIENT_EMAIL:-kornatskyy.pn@ucu.edu.ua}"
  sender_email="${SENDER_EMAIL:-$recipient_email}"

  # 3. Deploy reports CloudFormation stack
  echo "==> [3/3] Deploying CloudFormation stack $REPORTS_STACK"
  aws cloudformation deploy \
    --stack-name "$REPORTS_STACK" \
    --template-file infra/reports.yaml \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides \
      "ProjectName=$PROJECT_NAME" \
      "ImageUri=$image" \
      "VpcId=$vpc_id" \
      "SubnetIds=$subnet_a,$subnet_b" \
      "SecurityGroupId=$sec_group" \
      "RouteTableId=$route_table" \
      "DatabaseUrl=$db_url" \
      "RecipientEmail=$recipient_email" \
      "SenderEmail=$sender_email" \
    --tags "${STACK_TAGS[@]}" \
    --no-fail-on-empty-changeset

  bucket="$(output "$REPORTS_STACK" ReportsBucketName)"
  queue_url="$(output "$REPORTS_STACK" ReportRequestsQueueUrl)"
  echo
  echo "Reports stack deployed successfully!"
  echo "  Reports bucket: s3://$bucket"
  echo "  SQS queue URL:  $queue_url"
  echo "  SES recipient:  $recipient_email"
}

main "$@"
