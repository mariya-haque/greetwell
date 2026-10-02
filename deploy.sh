#!/usr/bin/env bash
# Deploy Greetwell from AWS CloudShell (or any Linux/macOS shell with the AWS CLI).
#
#   git clone https://github.com/mariya-haque/greetwell && cd greetwell && bash deploy.sh
#
# Same steps as deploy.ps1: build the Lambda package, deploy the stack, upload
# the site, seed the demo assistant, and check the live URL end to end.
set -euo pipefail

STACK="${STACK:-greetwell}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION" AWS_PAGER=""
cd "$(dirname "$0")"
step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }

step "Checking the AWS connection"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ARN=$(aws sts get-caller-identity --query Arn --output text)
MASKED="********${ACCOUNT: -4}"
echo "Connected as ${ARN//$ACCOUNT/$MASKED} in $REGION"

step "Building the Lambda package"
rm -rf build && mkdir build
python3 -m pip install --quiet --disable-pip-version-check --target build \
  --platform manylinux2014_x86_64 --implementation cp --python-version 3.13 --only-binary=:all: \
  "anthropic[bedrock]"
# The Lambda runtime already ships boto3.
rm -rf build/boto3* build/botocore* build/s3transfer* build/bin
cp -r backend/app build/app
find build -name __pycache__ -type d -prune -exec rm -rf {} +
echo "Package is $(du -sm build | cut -f1) MB"

step "Deploying the CloudFormation stack '$STACK' (about 5-10 minutes the first time)"
ARTIFACTS="$STACK-deploy-$ACCOUNT-$REGION"
aws s3api head-bucket --bucket "$ARTIFACTS" >/dev/null 2>&1 || aws s3 mb "s3://$ARTIFACTS" >/dev/null
aws cloudformation package --template-file template.yaml --s3-bucket "$ARTIFACTS" \
  --output-template-file build/packaged.yaml >/dev/null
OVERRIDES=()
[ -n "${MODEL_ID:-}" ] && OVERRIDES+=("ModelId=$MODEL_ID")
[ -n "${ALERT_EMAIL:-}" ] && OVERRIDES+=("AlertEmail=$ALERT_EMAIL")
aws cloudformation deploy --template-file build/packaged.yaml --stack-name "$STACK" \
  --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND --no-fail-on-empty-changeset \
  ${OVERRIDES[@]+--parameter-overrides "${OVERRIDES[@]}"}

out() { aws cloudformation describe-stacks --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
SITE=$(out SiteUrl)

step "Uploading the website"
aws s3 sync web "s3://$(out SiteBucketName)" --delete --exclude "*.html" --exclude "widget.js" --cache-control "public, max-age=3600" >/dev/null
aws s3 sync web "s3://$(out SiteBucketName)" --exclude "*" --include "*.html" --include "widget.js" --cache-control "public, max-age=300" >/dev/null
aws cloudfront create-invalidation --distribution-id "$(out DistributionId)" --paths "/*" >/dev/null

step "Seeding the demo assistant (this calls the model once)"
aws lambda invoke --function-name "$(out BuilderFunctionName)" --cli-binary-format raw-in-base64-out \
  --payload '{"action":"seed_demo"}' --cli-read-timeout 300 build/seed-result.json >/dev/null
cat build/seed-result.json; echo

step "Verifying the live site"
CHECKS=()
probe() {
  local name="$1"; shift
  if result=$("$@" 2>&1); then CHECKS+=("PASS  $name  ${result:0:160}"); printf '\033[32mPASS\033[0m  %s  %s\n' "$name" "${result:0:160}"
  else CHECKS+=("FAIL  $name  ${result:0:160}"); printf '\033[31mFAIL\033[0m  %s  %s\n' "$name" "${result:0:160}"; fi
}
probe "home page" curl -sfo /dev/null -w "%{http_code}" "$SITE/"
probe "widget script" curl -sfo /dev/null -w "%{http_code}" "$SITE/widget.js"
probe "api health" curl -sf "$SITE/api/health"
probe "demo assistant ready" bash -c "curl -sf '$SITE/api/bots/demo/public' | grep -q '\"status\": \"ready\"' && echo ready"
probe "live model reply" curl -sf -X POST "$SITE/api/chat" -H "Content-Type: application/json" \
  -d "{\"botId\":\"demo\",\"sessionId\":\"deploycheck_$(date +%s)00000000\",\"message\":\"In one sentence, what is Greetwell?\"}"

mkdir -p docs/proof
{
  echo "Greetwell - connected to AWS"
  echo "Recorded by deploy.sh on $(date -u '+%Y-%m-%d %H:%M') UTC"
  echo
  echo "\$ aws sts get-caller-identity"
  echo "Account: $MASKED"
  echo "Arn:     ${ARN//$ACCOUNT/$MASKED}"
  echo "Region:  $REGION"
  echo
  echo "\$ aws cloudformation describe-stack-resources --stack-name $STACK"
  aws cloudformation describe-stack-resources --stack-name "$STACK" --query "StackResources[].[ResourceType,ResourceStatus]" --output text
  echo
  echo "Live URL: $SITE"
  echo
  echo "Post-deploy checks"
  printf '%s\n' "${CHECKS[@]}"
} > docs/proof/aws-connection.txt

printf '\n\033[32mLive at: %s\033[0m\n' "$SITE"
echo "Proof of connection written to docs/proof/aws-connection.txt"
printf '%s\n' "${CHECKS[@]}" | grep -q '^FAIL' && exit 1 || exit 0
