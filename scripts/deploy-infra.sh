#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <subscription-id> <resource-group> <location> [app-name]"
  echo "Optional env vars: STATIC_WEB_APP_LOCATION"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

require_command az
require_command jq

REPO_ROOT="$(repo_root)"
TEMPLATE_FILE="$REPO_ROOT/infra/main.bicep"
OUTPUT_FILE="$(output_file_path)"
SUBSCRIPTION_ID="$1"
RESOURCE_GROUP="$2"
LOCATION="$3"
APP_NAME="${4:-clock}"
APP_NAME="$(lowercase "$APP_NAME")"
STATIC_WEB_APP_LOCATION="${STATIC_WEB_APP_LOCATION:-Central US}"

validate_app_name "$APP_NAME"
[[ -f "$TEMPLATE_FILE" ]] || die "Missing infrastructure template: $TEMPLATE_FILE"

info "Setting Azure subscription to $SUBSCRIPTION_ID"
az account set --subscription "$SUBSCRIPTION_ID"

info "Ensuring resource group exists: $RESOURCE_GROUP ($LOCATION)"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" >/dev/null

info "Deploying Static Web App infrastructure"
DEPLOY_OUTPUT_JSON="$(az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --template-file "$TEMPLATE_FILE" \
  --parameters \
    location="$LOCATION" \
    staticWebAppLocation="$STATIC_WEB_APP_LOCATION" \
    appName="$APP_NAME" \
  --query properties.outputs \
  -o json)"

printf '%s\n' "$DEPLOY_OUTPUT_JSON" > "$OUTPUT_FILE"

STATIC_WEB_APP_NAME="$(read_output_value "$OUTPUT_FILE" '.staticWebAppName.value')"
DEFAULT_HOSTNAME="$(read_output_value "$OUTPUT_FILE" '.defaultHostname.value')"
STATIC_WEB_APP_ID="$(read_output_value "$OUTPUT_FILE" '.staticWebAppId.value')"

info "Infrastructure deployment complete."
printf 'Static Web App name: %s\n' "$STATIC_WEB_APP_NAME"
printf 'Default hostname: %s\n' "$DEFAULT_HOSTNAME"
printf 'Static Web App ID: %s\n' "$STATIC_WEB_APP_ID"
printf 'Outputs file: %s\n' "$OUTPUT_FILE"
