#!/usr/bin/env bash
# Deploy team49 backend stacks to AWS.
#
# This script uses the AWS CLI for identity checks, CDK bootstrap detection,
# and post-deploy CloudFormation outputs. Stack provisioning runs through
# AWS CDK (CloudFormation under the hood), which is required for Lambda assets
# and the rest of this repo's infrastructure.
#
# Prerequisites:
#   - AWS CLI v2 configured (aws configure or SSO, etc.)
#   - Node.js 18+ (for the CDK CLI; Python CDK apps still use the Node cdk binary)
#   - uv (recommended; can install Python 3.12) or Python 3.12+ on PATH for pip fallback
#
# Usage:
#   ./scripts/deploy_aws.sh
#   AWS_REGION=us-west-2 ./scripts/deploy_aws.sh
#   DESTROY_EXISTING=1 ./scripts/deploy_aws.sh   # wipe app stacks then deploy (data loss)
#
# Environment:
#   AWS_REGION / AWS_DEFAULT_REGION  Target region (default: us-east-1)
#   DRY_RUN=1                        Run cdk synth instead of deploy
#   SKIP_BOOTSTRAP=1                 Do not run cdk bootstrap when CDKToolkit is missing
#   DESTROY_EXISTING=1               Before deploy: cdk destroy --all (deletes app data; opt-in; skipped when DRY_RUN=1)
#   CDK_EXTRA_ARGS                   Extra args passed to cdk deploy (quoted string)
#   CDK_DESTROY_EXTRA_ARGS           Extra args passed to cdk destroy (e.g. --verbose)
#   DEPLOY_UV_PYTHON                 Python version for uv venv (default: 3.12)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA="${ROOT}/infra"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
export AWS_DEFAULT_REGION="${REGION}"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

command -v aws >/dev/null 2>&1 || die "AWS CLI not found. Install https://aws.amazon.com/cli/"
command -v node >/dev/null 2>&1 || die "Node.js not found (required for CDK CLI)."

resolve_cdk() {
  if command -v cdk >/dev/null 2>&1; then
    echo cdk
  else
    echo "npx --yes aws-cdk@2"
  fi
}
CDK_BIN="$(resolve_cdk)"

echo "==> AWS caller identity"
aws sts get-caller-identity --output table
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
[[ -n "${ACCOUNT}" && "${ACCOUNT}" != "None" ]] || die "Could not resolve AWS account ID."

export CDK_DEFAULT_ACCOUNT="${ACCOUNT}"
export CDK_DEFAULT_REGION="${REGION}"

echo "==> Target account ${ACCOUNT} region ${REGION}"

# CDK runs `python app.py` from cdk.json. Prepare the venv before any cdk command (Windows PATH).
echo "==> Python venv and CDK app dependencies (${INFRA})"
cd "${INFRA}"
if command -v uv >/dev/null 2>&1; then
  UV_PY="${DEPLOY_UV_PYTHON:-3.12}"
  uv venv --python "${UV_PY}" .venv
  if [[ -f .venv/Scripts/activate ]]; then
    # shellcheck source=/dev/null
    source .venv/Scripts/activate
  else
    # shellcheck source=/dev/null
    source .venv/bin/activate
  fi
  uv pip install -r requirements.txt
else
  command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1 || die "No uv and no python on PATH. Install uv or Python 3.12+."
  PY="python3"
  command -v python3 >/dev/null 2>&1 || PY="python"
  "${PY}" -m venv .venv
  if [[ -f .venv/Scripts/activate ]]; then
    # shellcheck source=/dev/null
    source .venv/Scripts/activate
  else
    # shellcheck source=/dev/null
    source .venv/bin/activate
  fi
  pip install -r requirements.txt
fi
command -v python >/dev/null 2>&1 || die "venv active but python not found (check .venv)."
python -c "import sys; print('Using Python:', sys.executable)"

CDK_CONTEXT=( -c "account=${ACCOUNT}" -c "region=${REGION}" )

echo "==> CDK bootstrap status (AWS CLI: describe-stacks CDKToolkit)"
if aws cloudformation describe-stacks --stack-name CDKToolkit --region "${REGION}" --output text \
  --query 'Stacks[0].StackStatus' >/dev/null 2>&1; then
  echo "    CDKToolkit stack exists in ${REGION}."
else
  if [[ "${SKIP_BOOTSTRAP:-0}" == "1" ]]; then
    die "CDKToolkit not found and SKIP_BOOTSTRAP=1. Run: (cd infra && source .venv/Scripts/activate && cdk bootstrap aws://${ACCOUNT}/${REGION})"
  fi
  echo "    CDKToolkit not found; running cdk bootstrap aws://${ACCOUNT}/${REGION}"
  eval "${CDK_BIN} bootstrap aws://${ACCOUNT}/${REGION}"
fi

if [[ "${DRY_RUN:-0}" != "1" ]] && [[ "${DESTROY_EXISTING:-0}" == "1" ]]; then
  echo "================================================================================"
  echo "DESTROY_EXISTING=1: removing all stacks defined by this CDK app in ${REGION}."
  echo "This deletes application data (S3, DynamoDB, Neptune, KB, etc.) per stack removal policies."
  echo "CDKToolkit (bootstrap) is NOT removed. Unset DESTROY_EXISTING to skip destroy on future runs."
  echo "================================================================================"
  set +e
  # shellcheck disable=SC2086
  eval "${CDK_BIN} destroy --all --force" "${CDK_CONTEXT[@]}" ${CDK_DESTROY_EXTRA_ARGS:-}
  destroy_rc=$?
  set -e
  if [[ "${destroy_rc}" -ne 0 ]]; then
    echo "WARN: cdk destroy exited ${destroy_rc}. Continuing with deploy (common if stacks never existed)."
  fi
fi

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "==> DRY_RUN=1: cdk synth only"
  eval "${CDK_BIN} synth" "${CDK_CONTEXT[@]}"
  echo "OK: synth complete. cdk.out is under ${INFRA}/cdk.out"
  exit 0
fi

echo "==> cdk deploy --all (CloudFormation stacks)"
# shellcheck disable=SC2086
eval "${CDK_BIN} deploy --all --require-approval never" "${CDK_CONTEXT[@]}" ${CDK_EXTRA_ARGS:-}

echo ""
echo "==> Useful outputs (AWS CLI: CloudFormation describe-stacks)"
for STACK in Team49StorageStack Team49ApiStack; do
  if aws cloudformation describe-stacks --stack-name "${STACK}" --region "${REGION}" &>/dev/null; then
    echo "--- ${STACK} ---"
    aws cloudformation describe-stacks --stack-name "${STACK}" --region "${REGION}" \
      --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table
  else
    echo "(stack ${STACK} not found or not deployed in this region)"
  fi
done

echo ""
echo "Next steps (from README):"
echo "  Seed demo: uv run scripts/seed_demo.py --raw-bucket <RawBucketName> --api-url <HttpApiUrl>"
echo "  Local UI:  cd frontend && npm install && VITE_API_URL=<HttpApiUrl> npm run dev"
echo "Frontend static hosting is not in this CDK app; build with npm run build and host separately if needed."
