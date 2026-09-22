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

# An apex domain cannot hold a CNAME (RFC 1034 — it would collide with the zone's
# mandatory SOA and NS records), so Azure validates it with a TXT token instead.
# Anything with a label in front of the registrable pair is a subdomain and uses
# CNAME delegation, which validates itself once DNS resolves.
DOT_COUNT="$(printf '%s' "$CUSTOM_DOMAIN" | tr -cd '.' | wc -c | tr -d ' ')"
if [[ "$DOT_COUNT" -le 1 ]]; then
  VALIDATION_METHOD="dns-txt-token"
else
  VALIDATION_METHOD="cname-delegation"
fi
info "Domain $CUSTOM_DOMAIN will be validated by $VALIDATION_METHOD."

if [[ "$VALIDATION_METHOD" = "cname-delegation" ]] && command -v dig >/dev/null 2>&1; then
  OBSERVED_CNAME="$(dig +short CNAME "$CUSTOM_DOMAIN" | sed 's/\.$//' | head -n 1)"
  if [[ -z "$OBSERVED_CNAME" ]]; then
    warn "DNS is not ready yet. No live CNAME was found for $CUSTOM_DOMAIN."
    printf 'Add this record, then re-run:\n  CNAME  %s  ->  %s\n' \
      "$CUSTOM_DOMAIN" "$EXPECTED_CNAME" >&2
    exit "$PENDING_DNS_EXIT_CODE"
  fi
  if [[ "$(lowercase "$OBSERVED_CNAME")" != "$(lowercase "$EXPECTED_CNAME")" ]]; then
    warn "DNS is not ready yet. $CUSTOM_DOMAIN points to $OBSERVED_CNAME but must point to $EXPECTED_CNAME."
    exit "$PENDING_DNS_EXIT_CODE"
  fi
  info "Live DNS CNAME matches the expected Static Web App hostname."
fi

set +e
SET_OUTPUT="$(az staticwebapp hostname set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$STATIC_WEB_APP_NAME" \
  --hostname "$CUSTOM_DOMAIN" \
  --validation-method "$VALIDATION_METHOD" \
  -o json 2>&1)"
SET_STATUS=$?
set -e

if [[ "$VALIDATION_METHOD" = "dns-txt-token" && "$SET_STATUS" -eq 0 ]]; then
  TOKEN="$(az staticwebapp hostname show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$STATIC_WEB_APP_NAME" \
    --hostname "$CUSTOM_DOMAIN" \
    --query validationToken -o tsv 2>/dev/null)"
  STATUS="$(az staticwebapp hostname show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$STATIC_WEB_APP_NAME" \
    --hostname "$CUSTOM_DOMAIN" \
    --query status -o tsv 2>/dev/null)"
  if [[ -n "$TOKEN" ]]; then
    printf '\nPublish these two records in DNS, both unproxied:\n\n'
    printf '  TXT    %s                 %s\n' "$CUSTOM_DOMAIN" "$TOKEN"
    printf '  CNAME  %s                 %s   (or an A record to the SWA inbound IP)\n\n' \
      "$CUSTOM_DOMAIN" "$EXPECTED_CNAME"
    printf 'Current status: %s. Re-run this script once the records resolve.\n' "$STATUS"
  fi
fi

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
