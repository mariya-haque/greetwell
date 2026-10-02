<#
.SYNOPSIS
  Build and deploy Greetwell to AWS, then verify that it is live.

.DESCRIPTION
  1. Confirms the AWS CLI is signed in (and records that as proof of connection).
  2. Builds the Lambda package with Linux wheels.
  3. Deploys the CloudFormation stack.
  4. Uploads the website, seeds the demo assistant, and smoke-tests the live URL.

  Safe to run again: every step is idempotent.

.EXAMPLE
  .\deploy.ps1
  .\deploy.ps1 -Region us-west-2 -ModelId anthropic.claude-haiku-4-5
  .\deploy.ps1 -AlertEmail you@example.com     # also email me if monthly AWS spend passes $40
#>
param(
  [string]$StackName = "greetwell",
  [string]$Region = "",
  [string]$ModelId = "",
  [string]$AlertEmail = "",
  [switch]$SkipModelCheck
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)." } }

# --- tools -------------------------------------------------------------------
$aws = (Get-Command aws -ErrorAction SilentlyContinue).Source
if (-not $aws) { $aws = "C:\Program Files\Amazon\AWSCLIV2\aws.exe" }
if (-not (Test-Path $aws)) { throw "AWS CLI not found. Install it with: winget install Amazon.AWSCLI" }
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = (Get-Command python).Source }

if (-not $Region) { $Region = $env:AWS_REGION }
if (-not $Region) { $Region = (& $aws configure get region) }
if (-not $Region) { $Region = "us-east-1" }
$env:AWS_REGION = $Region
$env:AWS_DEFAULT_REGION = $Region
$env:AWS_PAGER = ""

# --- 1. connection -----------------------------------------------------------
Step "Checking the AWS connection"
$identityJson = & $aws sts get-caller-identity --output json
if ($LASTEXITCODE -ne 0) {
  throw "The AWS CLI is not signed in. Run 'aws configure' (or 'aws login') in a terminal, then run this script again."
}
$identity = $identityJson | ConvertFrom-Json
$account = $identity.Account
$masked = ("*" * 8) + $account.Substring($account.Length - 4)
Write-Host "Connected as $($identity.Arn -replace $account, $masked) in $Region"

# --- 2. model access ---------------------------------------------------------
if (-not $SkipModelCheck) {
  Step "Checking which Claude models this account can use on Amazon Bedrock"
  & $python (Join-Path $root "scripts\check_bedrock.py") --region $Region
  if ($LASTEXITCODE -ne 0) {
    throw "No Claude model answered. Open the Amazon Bedrock console, enable model access for Anthropic models in $Region, then run this script again."
  }
}

# --- 3. build ----------------------------------------------------------------
Step "Building the Lambda package"
$build = Join-Path $root "build"
if (Test-Path $build) { Remove-Item -Recurse -Force $build }
New-Item -ItemType Directory -Force $build | Out-Null
& $python -m pip install --quiet --disable-pip-version-check --target $build `
  --platform manylinux2014_x86_64 --implementation cp --python-version 3.13 --only-binary=:all: `
  "anthropic[bedrock]"
Check "Installing dependencies"
# The Lambda runtime already ships boto3, so leave the 90 MB copy out of the package.
foreach ($name in "boto3", "botocore", "s3transfer") {
  Get-ChildItem $build -Directory -Filter "$name*" | Remove-Item -Recurse -Force
}
if (Test-Path (Join-Path $build "bin")) { Remove-Item -Recurse -Force (Join-Path $build "bin") }
Copy-Item -Recurse (Join-Path $root "backend\app") (Join-Path $build "app")
Get-ChildItem $build -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
$sizeMb = [math]::Round(((Get-ChildItem $build -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host "Package is $sizeMb MB unzipped"

# --- 4. deploy ---------------------------------------------------------------
Step "Deploying the CloudFormation stack '$StackName' (the first run takes about 5 minutes)"
$artifacts = "$StackName-deploy-$account-$Region"
# Windows PowerShell turns redirected stderr into errors, so relax the preference for this probe.
$ErrorActionPreference = "Continue"
& $aws s3api head-bucket --bucket $artifacts 2>&1 | Out-Null
$bucketMissing = $LASTEXITCODE -ne 0
$ErrorActionPreference = "Stop"
if ($bucketMissing) {
  & $aws s3 mb "s3://$artifacts" --region $Region | Out-Null
  Check "Creating the deployment bucket"
}
$packaged = Join-Path $root "build\packaged.yaml"
& $aws cloudformation package --template-file (Join-Path $root "template.yaml") `
  --s3-bucket $artifacts --output-template-file $packaged | Out-Null
Check "Packaging"
$deployArgs = @(
  "cloudformation", "deploy", "--template-file", $packaged, "--stack-name", $StackName,
  "--capabilities", "CAPABILITY_IAM", "CAPABILITY_AUTO_EXPAND", "--no-fail-on-empty-changeset"
)
$overrides = @()
if ($ModelId) { $overrides += "ModelId=$ModelId" }
if ($AlertEmail) { $overrides += "AlertEmail=$AlertEmail" }
if ($overrides) { $deployArgs += @("--parameter-overrides") + $overrides }
& $aws @deployArgs
Check "Deploying the stack"

$outputs = @{}
(& $aws cloudformation describe-stacks --stack-name $StackName --query "Stacks[0].Outputs" --output json | ConvertFrom-Json) |
  ForEach-Object { $outputs[$_.OutputKey] = $_.OutputValue }
$site = $outputs["SiteUrl"]

# --- 5. website --------------------------------------------------------------
Step "Uploading the website"
$web = Join-Path $root "web"
$bucket = "s3://$($outputs['SiteBucketName'])"
& $aws s3 sync $web $bucket --delete --exclude "*.html" --exclude "widget.js" --cache-control "public, max-age=3600" | Out-Null
Check "Uploading assets"
& $aws s3 sync $web $bucket --exclude "*" --include "*.html" --include "widget.js" --cache-control "public, max-age=300" | Out-Null
Check "Uploading pages"
& $aws cloudfront create-invalidation --distribution-id $outputs["DistributionId"] --paths "/*" | Out-Null
Check "Refreshing the CDN"

# --- 6. demo assistant -------------------------------------------------------
Step "Seeding the demo assistant (this calls the model once)"
$payload = Join-Path $build "seed.json"
$result = Join-Path $build "seed-result.json"
[IO.File]::WriteAllText($payload, '{"action":"seed_demo"}')
& $aws lambda invoke --function-name $outputs["BuilderFunctionName"] --payload "fileb://$payload" `
  --cli-read-timeout 300 $result | Out-Null
Check "Seeding the demo assistant"
$seed = Get-Content $result -Raw | ConvertFrom-Json
Write-Host "Demo assistant: status=$($seed.status) model=$($seed.model) profileFromModel=$($seed.profileFromModel) $($seed.error)"

# --- 7. verify ---------------------------------------------------------------
Step "Verifying the live site"
$checks = @()
function Probe($name, $block) {
  try { $value = & $block; $script:checks += "PASS  $name  $value"; Write-Host "PASS  $name  $value" -ForegroundColor Green }
  catch { $script:checks += "FAIL  $name  $($_.Exception.Message)"; Write-Host "FAIL  $name  $($_.Exception.Message)" -ForegroundColor Red }
}
Probe "home page" { (Invoke-WebRequest "$site/" -UseBasicParsing).StatusCode }
Probe "widget script" { (Invoke-WebRequest "$site/widget.js" -UseBasicParsing).StatusCode }
Probe "api health" { (Invoke-RestMethod "$site/api/health").ok }
Probe "demo assistant ready" { $b = Invoke-RestMethod "$site/api/bots/demo/public"; if ($b.status -ne "ready") { throw "status is $($b.status)" }; $b.name }
Probe "live model reply" {
  $body = @{ botId = "demo"; sessionId = "deploycheck_" + [guid]::NewGuid().ToString("N"); message = "In one sentence, what is Greetwell?" } | ConvertTo-Json
  (Invoke-RestMethod "$site/api/chat" -Method Post -ContentType "application/json" -Body $body).reply
}

# --- proof of connection -----------------------------------------------------
$proofDir = Join-Path $root "docs\proof"
New-Item -ItemType Directory -Force $proofDir | Out-Null
$resources = & $aws cloudformation describe-stack-resources --stack-name $StackName `
  --query "StackResources[].[ResourceType,ResourceStatus]" --output text
@(
  "Greetwell - coding agent connected to AWS",
  "Recorded by deploy.ps1 on $((Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm')) UTC",
  "",
  "$ aws sts get-caller-identity",
  "Account: $masked",
  "Arn:     $($identity.Arn -replace $account, $masked)",
  "Region:  $Region",
  "",
  "$ aws cloudformation describe-stack-resources --stack-name $StackName",
  $resources,
  "",
  "Live URL: $site",
  "",
  "Post-deploy checks",
  $checks
) | Out-File -Encoding utf8 (Join-Path $proofDir "aws-connection.txt")

Write-Host "`nLive at: $site" -ForegroundColor Green
Write-Host "Proof of connection written to docs\proof\aws-connection.txt"
if ($checks -match "^FAIL") { exit 1 }
