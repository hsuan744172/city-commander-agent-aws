#!/usr/bin/env bash
# Deploy the complete City Commander application (React + FastAPI) to AWS App Runner.
# Prerequisites: a secure AWS CLI profile/role, Docker Buildx, ECR/App Runner/IAM permissions,
# and Amazon Bedrock model access for Claude Sonnet 5 in the selected region.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="${SERVICE_NAME:-city-commander-agent}"
ECR_REPOSITORY="${ECR_REPOSITORY:-city-commander-agent}"
AWS_REGION="${AWS_REGION:-us-west-2}"
MODEL_ID="${BEDROCK_MODEL_ID:-us.anthropic.claude-sonnet-5}"
IMAGE_TAG="${IMAGE_TAG:-$(date -u +%Y%m%d%H%M%S)}"
INSTANCE_ROLE_NAME="${INSTANCE_ROLE_NAME:-CityCommanderAppRunnerInstanceRole}"
ECR_ACCESS_ROLE_NAME="${ECR_ACCESS_ROLE_NAME:-CityCommanderAppRunnerEcrAccessRole}"

require_command() {
  command -v "$1" >/dev/null 2>&1 || { echo "Required command not found: $1" >&2; exit 1; }
}

require_command aws
require_command docker

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text --region "$AWS_REGION")"
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}"
IMAGE_URI="${ECR_URI}:${IMAGE_TAG}"

ensure_role() {
  local role_name="$1"
  local trust_policy="$2"
  if ! aws iam get-role --role-name "$role_name" >/dev/null 2>&1; then
    aws iam create-role \
      --role-name "$role_name" \
      --assume-role-policy-document "file://${trust_policy}" >/dev/null
  else
    aws iam update-assume-role-policy \
      --role-name "$role_name" \
      --policy-document "file://${trust_policy}"
  fi
}

ensure_role "$INSTANCE_ROLE_NAME" "$PROJECT_ROOT/deployment/iam/app-runner-instance-trust-policy.json"
ensure_role "$ECR_ACCESS_ROLE_NAME" "$PROJECT_ROOT/deployment/iam/app-runner-ecr-access-trust-policy.json"

aws iam put-role-policy \
  --role-name "$INSTANCE_ROLE_NAME" \
  --policy-name "CityCommanderBedrockClaudeSonnet5" \
  --policy-document "file://$PROJECT_ROOT/deployment/iam/bedrock-claude-sonnet-5-policy.json"

aws iam attach-role-policy \
  --role-name "$ECR_ACCESS_ROLE_NAME" \
  --policy-arn "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"

INSTANCE_ROLE_ARN="$(aws iam get-role --role-name "$INSTANCE_ROLE_NAME" --query 'Role.Arn' --output text)"
ECR_ACCESS_ROLE_ARN="$(aws iam get-role --role-name "$ECR_ACCESS_ROLE_NAME" --query 'Role.Arn' --output text)"

if ! aws ecr describe-repositories --repository-names "$ECR_REPOSITORY" --region "$AWS_REGION" >/dev/null 2>&1; then
  aws ecr create-repository --repository-name "$ECR_REPOSITORY" --region "$AWS_REGION" >/dev/null
fi

aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_URI"
docker buildx build \
  --platform linux/amd64 \
  --file "$PROJECT_ROOT/backend/Dockerfile" \
  --tag "$IMAGE_URI" \
  --push \
  "$PROJECT_ROOT"

SOURCE_CONFIGURATION_FILE="$(mktemp)"
trap 'rm -f "$SOURCE_CONFIGURATION_FILE"' EXIT
cat >"$SOURCE_CONFIGURATION_FILE" <<EOF
{
  "AutoDeploymentsEnabled": false,
  "AuthenticationConfiguration": {
    "AccessRoleArn": "$ECR_ACCESS_ROLE_ARN"
  },
  "ImageRepository": {
    "ImageIdentifier": "$IMAGE_URI",
    "ImageRepositoryType": "ECR",
    "ImageConfiguration": {
      "Port": "8080",
      "RuntimeEnvironmentVariables": {
        "APP_AWS_REGION": "$AWS_REGION",
        "BEDROCK_MODEL_ID": "$MODEL_ID",
        "PORT": "8080"
      }
    }
  }
}
EOF

HEALTH_CHECK_CONFIGURATION='{"Protocol":"HTTP","Path":"/api/health","Interval":10,"Timeout":5,"HealthyThreshold":1,"UnhealthyThreshold":5}'
INSTANCE_CONFIGURATION="{\"Cpu\":\"1 vCPU\",\"Memory\":\"2 GB\",\"InstanceRoleArn\":\"$INSTANCE_ROLE_ARN\"}"
SERVICE_ARN="$(aws apprunner list-services --region "$AWS_REGION" --query "ServiceSummaryList[?ServiceName=='$SERVICE_NAME'].ServiceArn | [0]" --output text)"

# IAM role propagation is asynchronous; App Runner can reject a newly-created role briefly.
sleep 10
if [[ -z "$SERVICE_ARN" || "$SERVICE_ARN" == "None" ]]; then
  SERVICE_ARN="$(aws apprunner create-service \
    --service-name "$SERVICE_NAME" \
    --source-configuration "file://$SOURCE_CONFIGURATION_FILE" \
    --instance-configuration "$INSTANCE_CONFIGURATION" \
    --health-check-configuration "$HEALTH_CHECK_CONFIGURATION" \
    --region "$AWS_REGION" \
    --query 'Service.ServiceArn' \
    --output text)"
else
  aws apprunner update-service \
    --service-arn "$SERVICE_ARN" \
    --source-configuration "file://$SOURCE_CONFIGURATION_FILE" \
    --instance-configuration "$INSTANCE_CONFIGURATION" \
    --health-check-configuration "$HEALTH_CHECK_CONFIGURATION" \
    --region "$AWS_REGION" >/dev/null
fi

aws apprunner wait service-running --service-arn "$SERVICE_ARN" --region "$AWS_REGION"
SERVICE_URL="$(aws apprunner describe-service --service-arn "$SERVICE_ARN" --region "$AWS_REGION" --query 'Service.ServiceUrl' --output text)"
printf '\nDeployment complete: https://%s\nHealth check: https://%s/api/health\n' "$SERVICE_URL" "$SERVICE_URL"
