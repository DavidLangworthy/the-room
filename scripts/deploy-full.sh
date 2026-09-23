#!/usr/bin/env bash

set -euo pipefail

PENDING_DNS_EXIT_CODE=20

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <subscription-id> <resource-group> <location> [app-name]"
  echo "Optional env vars: STATIC_WEB_APP_LOCATION, CUSTOM_DOMAIN, SITE_DIR"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

require_command jq

SUBSCRIPTION_ID="$1"
RESOURCE_GROUP="$2"
LOCATION="$3"
APP_NAME="${4:-clock}"
OUTPUT_FILE="$(output_file_path)"
SITE_DIR="${SITE_DIR:-site}"

info "Step 1/3: Deploying infrastructure"
"$SCRIPT_DIR/deploy-infra.sh" "$SUBSCRIPTION_ID" "$RESOURCE_GROUP" "$LOCATION" "$APP_NAME"

STATIC_WEB_APP_NAME="$(read_output_value "$OUTPUT_FILE" '.staticWebAppName.value')"
DEFAULT_HOSTNAME="$(read_output_value "$OUTPUT_FILE" '.defaultHostname.value')"

info "Step 2/3: Deploying frontend"
"$SCRIPT_DIR/deploy-frontend.sh" "$RESOURCE_GROUP" "$STATIC_WEB_APP_NAME" "$SITE_DIR"

if [[ -n "${CUSTOM_DOMAIN:-}" ]]; then
  info "Step 3/3: Configuring custom domain ${CUSTOM_DOMAIN}"
  set +e
  "$SCRIPT_DIR/configure-custom-domain.sh" "$RESOURCE_GROUP" "$STATIC_WEB_APP_NAME" "$CUSTOM_DOMAIN"
  DOMAIN_STATUS=$?
  set -e

  if [[ "$DOMAIN_STATUS" -eq "$PENDING_DNS_EXIT_CODE" ]]; then
    info "Deployment succeeded, but DNS is not ready for ${CUSTOM_DOMAIN} yet."
    printf 'Add the required CNAME record, wait for DNS propagation, and rerun this script.\n'
    printf 'Default hostname: %s\n' "$DEFAULT_HOSTNAME"
    exit 0
  fi

  [[ "$DOMAIN_STATUS" -eq 0 ]] || exit "$DOMAIN_STATUS"
else
  info "Step 3/3: Skipping custom domain configuration because CUSTOM_DOMAIN is not set."
fi

info "Full deployment complete."
printf 'Default hostname: %s\n' "$DEFAULT_HOSTNAME"
if [[ -n "${CUSTOM_DOMAIN:-}" ]]; then
  printf 'Custom domain: %s\n' "$CUSTOM_DOMAIN"
fi
