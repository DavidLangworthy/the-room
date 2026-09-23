#!/usr/bin/env bash

set -euo pipefail

PENDING_DNS_EXIT_CODE=20

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <resource-group> <static-web-app-name> <custom-domain>"
  echo "Exit code $PENDING_DNS_EXIT_CODE means the required DNS CNAME is not live yet."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

require_command az

looks_like_pending_dns_error() {
  local raw_message="$1"
  local message

  message="$(lowercase "$raw_message")"

  [[ "$message" == *"validation"* || "$message" == *"cname"* || "$message" == *"dns"* || "$message" == *"txt"* ]]
}

RESOURCE_GROUP="$1"
STATIC_WEB_APP_NAME="$2"
CUSTOM_DOMAIN="$(lowercase "$3")"
HOST_ONLY_LABEL="${CUSTOM_DOMAIN%%.*}"

DEFAULT_HOSTNAME="$(az staticwebapp show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$STATIC_WEB_APP_NAME" \
  --query defaultHostname \
  -o tsv)"

[[ -n "$DEFAULT_HOSTNAME" ]] || die "Failed to resolve the default hostname for $STATIC_WEB_APP_NAME"

printf 'Required DNS record:\n'
printf '  Type: CNAME\n'
printf '  Name: %s\n' "$CUSTOM_DOMAIN"
printf '  Value: %s\n' "$DEFAULT_HOSTNAME"
printf '  Host-only label (if required by your DNS provider): %s\n' "$HOST_ONLY_LABEL"

EXISTING_STATUS="$(az staticwebapp hostname list \
  --resource-group "$RESOURCE_GROUP" \
  --name "$STATIC_WEB_APP_NAME" \
  --query "[?domainName=='$CUSTOM_DOMAIN'].status | [0]" \
  -o tsv)"

if [[ -n "$EXISTING_STATUS" ]]; then
  info "Custom domain already configured with status: $EXISTING_STATUS"
  exit 0
fi

EXPECTED_CNAME="${DEFAULT_HOSTNAME%.}"

if command -v dig >/dev/null 2>&1; then
  OBSERVED_CNAME="$(dig +short CNAME "$CUSTOM_DOMAIN" | sed 's/\.$//' | head -n 1)"
  if [[ -z "$OBSERVED_CNAME" ]]; then
    warn "DNS is not ready yet. No live CNAME was found for $CUSTOM_DOMAIN."
    exit "$PENDING_DNS_EXIT_CODE"
  fi

  if [[ "$(lowercase "$OBSERVED_CNAME")" != "$(lowercase "$EXPECTED_CNAME")" ]]; then
    warn "DNS is not ready yet. $CUSTOM_DOMAIN points to $OBSERVED_CNAME but must point to $EXPECTED_CNAME."
    exit "$PENDING_DNS_EXIT_CODE"
  fi

  info "Live DNS CNAME matches the expected Static Web App hostname."
else
  warn "dig is not available. Falling back to Azure hostname validation."
fi

set +e
SET_OUTPUT="$(az staticwebapp hostname set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$STATIC_WEB_APP_NAME" \
  --hostname "$CUSTOM_DOMAIN" \
  --validation-method cname-delegation \
  -o json 2>&1)"
SET_STATUS=$?
set -e

if [[ "$SET_STATUS" -ne 0 ]]; then
  if ! command -v dig >/dev/null 2>&1 && looks_like_pending_dns_error "$SET_OUTPUT"; then
    warn "Azure could not validate the custom domain yet."
    printf '%s\n' "$SET_OUTPUT" >&2
    exit "$PENDING_DNS_EXIT_CODE"
  fi

  printf '%s\n' "$SET_OUTPUT" >&2
  die "Failed to configure custom domain $CUSTOM_DOMAIN"
fi

FINAL_STATUS="$(az staticwebapp hostname list \
  --resource-group "$RESOURCE_GROUP" \
  --name "$STATIC_WEB_APP_NAME" \
  --query "[?domainName=='$CUSTOM_DOMAIN'].status | [0]" \
  -o tsv)"

[[ -n "$FINAL_STATUS" ]] || die "Azure accepted the custom domain command, but the hostname is not listed yet."

info "Custom domain configured with status: $FINAL_STATUS"
