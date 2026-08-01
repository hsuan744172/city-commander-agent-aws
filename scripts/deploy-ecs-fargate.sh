#!/usr/bin/env bash
# Deploy the City Commander application to ECS Fargate behind an internet-facing ALB.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_REGION="${AWS_REGION:-us-west-2}"
SERVICE_NAME="${SERVICE_NAME:-city-commander-agent}"
CLUSTER_NAME="${CLUSTER_NAME:-city-commander-cluster}"
ECR_REPOSITORY="${ECR_REPOSITORY:-city-commander-agent}"
MODEL_ID="${BEDROCK_MODEL_ID:-us.anthropic.claude-sonnet-4-6}"
TASK_EXECUTION_ROLE_NAME="${TASK_EXECUTION_ROLE_NAME:-CityCommanderEcsTaskExecutionRole}"
TASK_ROLE_NAME="${TASK_ROLE_NAME:-CityCommanderEcsTaskRole}"
ALB_NAME="${ALB_NAME:-city-commander-alb}"
TARGET_GROUP_NAME="${TARGET_GROUP_NAME:-city-commander-tg}"
TASK_FAMILY="${TASK_FAMILY:-city-commander-agent}"

require_command() {
  command -v "$1" >/dev/null 2>&1 || { echo "Required command not found: $1" >&2; exit 1; }
}
require_command aws
require_command docker

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text --region "$AWS_REGION")"
IMAGE_TAG="${IMAGE_TAG:-$(date -u +%Y%m%d%H%M%S)}"
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}"
IMAGE_URI="${ECR_URI}:${IMAGE_TAG}"

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

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

cat >"$TEMP_DIR/ecs-task-trust.json" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "ecs-tasks.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
JSON

ensure_role() {
  local role_name="$1"
  if aws iam get-role --role-name "$role_name" >/dev/null 2>&1; then
    aws iam update-assume-role-policy \
      --role-name "$role_name" \
      --policy-document "file://$TEMP_DIR/ecs-task-trust.json" >/dev/null
  else
    aws iam create-role \
      --role-name "$role_name" \
      --assume-role-policy-document "file://$TEMP_DIR/ecs-task-trust.json" >/dev/null
  fi
}

ensure_role "$TASK_EXECUTION_ROLE_NAME"
ensure_role "$TASK_ROLE_NAME"
aws iam attach-role-policy \
  --role-name "$TASK_EXECUTION_ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
aws iam put-role-policy \
  --role-name "$TASK_ROLE_NAME" \
  --policy-name CityCommanderBedrockClaudeSonnet46 \
  --policy-document "file://$PROJECT_ROOT/deployment/iam/bedrock-claude-sonnet-4-6-policy.json"

TASK_EXECUTION_ROLE_ARN="$(aws iam get-role --role-name "$TASK_EXECUTION_ROLE_NAME" --query 'Role.Arn' --output text)"
TASK_ROLE_ARN="$(aws iam get-role --role-name "$TASK_ROLE_NAME" --query 'Role.Arn' --output text)"

if ! aws ecs describe-clusters --clusters "$CLUSTER_NAME" --region "$AWS_REGION" \
  --query 'clusters[?status==`ACTIVE`].clusterName | [0]' --output text | grep -qx "$CLUSTER_NAME"; then
  aws ecs create-cluster --cluster-name "$CLUSTER_NAME" --region "$AWS_REGION" >/dev/null
fi

VPC_ID="$(aws ec2 describe-vpcs --region "$AWS_REGION" \
  --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)"
SUBNET_TEXT="$(aws ec2 describe-subnets --region "$AWS_REGION" \
  --filters Name=vpc-id,Values="$VPC_ID" Name=default-for-az,Values=true \
  --query 'Subnets | sort_by(@,& AvailabilityZone)[].SubnetId' --output text)"
IFS=$'\t' read -r -a SUBNETS <<<"$SUBNET_TEXT"
if (( ${#SUBNETS[@]} < 2 )); then
  echo "At least two default subnets are required" >&2
  exit 1
fi
SUBNET_A="${SUBNETS[0]}"
SUBNET_B="${SUBNETS[1]}"

get_or_create_sg() {
  local name="$1"
  local description="$2"
  local sg_id
  sg_id="$(aws ec2 describe-security-groups --region "$AWS_REGION" \
    --filters Name=vpc-id,Values="$VPC_ID" Name=group-name,Values="$name" \
    --query 'SecurityGroups[0].GroupId' --output text)"
  if [[ -z "$sg_id" || "$sg_id" == "None" ]]; then
    sg_id="$(aws ec2 create-security-group --region "$AWS_REGION" \
      --group-name "$name" --description "$description" --vpc-id "$VPC_ID" \
      --query 'GroupId' --output text)"
  fi
  printf '%s' "$sg_id"
}

ALB_SG_ID="$(get_or_create_sg city-commander-alb-sg 'Public HTTP access for City Commander ALB')"
TASK_SG_ID="$(get_or_create_sg city-commander-task-sg 'ALB access to City Commander ECS tasks')"
aws ec2 authorize-security-group-ingress --region "$AWS_REGION" --group-id "$ALB_SG_ID" \
  --protocol tcp --port 80 --cidr 0.0.0.0/0 >/dev/null 2>&1 || true
aws ec2 authorize-security-group-ingress --region "$AWS_REGION" --group-id "$TASK_SG_ID" \
  --protocol tcp --port 8080 --source-group "$ALB_SG_ID" >/dev/null 2>&1 || true

ALB_ARN="$(aws elbv2 describe-load-balancers --region "$AWS_REGION" --names "$ALB_NAME" \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || true)"
if [[ -z "$ALB_ARN" || "$ALB_ARN" == "None" ]]; then
  ALB_ARN="$(aws elbv2 create-load-balancer --region "$AWS_REGION" \
    --name "$ALB_NAME" --type application --scheme internet-facing --ip-address-type ipv4 \
    --subnets "$SUBNET_A" "$SUBNET_B" --security-groups "$ALB_SG_ID" \
    --query 'LoadBalancers[0].LoadBalancerArn' --output text)"
fi

TARGET_GROUP_ARN="$(aws elbv2 describe-target-groups --region "$AWS_REGION" --names "$TARGET_GROUP_NAME" \
  --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null || true)"
if [[ -z "$TARGET_GROUP_ARN" || "$TARGET_GROUP_ARN" == "None" ]]; then
  TARGET_GROUP_ARN="$(aws elbv2 create-target-group --region "$AWS_REGION" \
    --name "$TARGET_GROUP_NAME" --protocol HTTP --port 8080 --target-type ip --vpc-id "$VPC_ID" \
    --health-check-protocol HTTP --health-check-path /api/health \
    --health-check-interval-seconds 10 --health-check-timeout-seconds 5 \
    --healthy-threshold-count 2 --unhealthy-threshold-count 5 \
    --query 'TargetGroups[0].TargetGroupArn' --output text)"
fi

LISTENER_ARN="$(aws elbv2 describe-listeners --region "$AWS_REGION" --load-balancer-arn "$ALB_ARN" \
  --query 'Listeners[?Port==`80`].ListenerArn | [0]' --output text)"
if [[ -z "$LISTENER_ARN" || "$LISTENER_ARN" == "None" ]]; then
  aws elbv2 create-listener --region "$AWS_REGION" --load-balancer-arn "$ALB_ARN" \
    --protocol HTTP --port 80 \
    --default-actions "Type=forward,TargetGroupArn=$TARGET_GROUP_ARN" >/dev/null
else
  aws elbv2 modify-listener --region "$AWS_REGION" --listener-arn "$LISTENER_ARN" \
    --default-actions "Type=forward,TargetGroupArn=$TARGET_GROUP_ARN" >/dev/null
fi

cat >"$TEMP_DIR/task-definition.json" <<JSON
{
  "family": "$TASK_FAMILY",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "1024",
  "memory": "2048",
  "executionRoleArn": "$TASK_EXECUTION_ROLE_ARN",
  "taskRoleArn": "$TASK_ROLE_ARN",
  "containerDefinitions": [{
    "name": "$SERVICE_NAME",
    "image": "$IMAGE_URI",
    "essential": true,
    "portMappings": [{"containerPort": 8080, "hostPort": 8080, "protocol": "tcp"}],
    "environment": [
      {"name": "APP_AWS_REGION", "value": "$AWS_REGION"},
      {"name": "BEDROCK_MODEL_ID", "value": "$MODEL_ID"},
      {"name": "PORT", "value": "8080"}
    ]
  }]
}
JSON

# New IAM roles can take a few seconds to become usable by ECS.
sleep 10
TASK_DEFINITION_ARN="$(aws ecs register-task-definition --region "$AWS_REGION" \
  --cli-input-json "file://$TEMP_DIR/task-definition.json" \
  --query 'taskDefinition.taskDefinitionArn' --output text)"

SERVICE_ARN="$(aws ecs describe-services --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" \
  --region "$AWS_REGION" --query 'services[?status!=`INACTIVE`].serviceArn | [0]' --output text)"
NETWORK_CONFIGURATION="awsvpcConfiguration={subnets=[$SUBNET_A,$SUBNET_B],securityGroups=[$TASK_SG_ID],assignPublicIp=ENABLED}"
if [[ -z "$SERVICE_ARN" || "$SERVICE_ARN" == "None" ]]; then
  aws ecs create-service --region "$AWS_REGION" --cluster "$CLUSTER_NAME" \
    --service-name "$SERVICE_NAME" --task-definition "$TASK_DEFINITION_ARN" \
    --desired-count 1 --launch-type FARGATE --platform-version LATEST \
    --network-configuration "$NETWORK_CONFIGURATION" \
    --load-balancers "targetGroupArn=$TARGET_GROUP_ARN,containerName=$SERVICE_NAME,containerPort=8080" \
    --health-check-grace-period-seconds 120 >/dev/null
else
  aws ecs update-service --region "$AWS_REGION" --cluster "$CLUSTER_NAME" \
    --service "$SERVICE_NAME" --task-definition "$TASK_DEFINITION_ARN" \
    --desired-count 1 --force-new-deployment \
    --network-configuration "$NETWORK_CONFIGURATION" \
    --health-check-grace-period-seconds 120 >/dev/null
fi

aws ecs wait services-stable --region "$AWS_REGION" --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME"
ALB_DNS="$(aws elbv2 describe-load-balancers --region "$AWS_REGION" \
  --load-balancer-arns "$ALB_ARN" --query 'LoadBalancers[0].DNSName' --output text)"
printf '\nDeployment complete: http://%s\nHealth check: http://%s/api/health\n' "$ALB_DNS" "$ALB_DNS"
