#!/usr/bin/env bash
#
# Attach a custom domain to the Static Web App, and tell the truth about whether
# it is actually finished.
#
# Two things this script learned the hard way:
#   * An apex domain cannot hold a CNAME — it would collide with the zone's
#     mandatory SOA and NS records (RFC 1034) — so Azure validates an apex with a
#     TXT token and a subdomain by CNAME delegation. Printing CNAME instructions
#     for an apex sends the operator down a road that cannot work.
#   * "Validating" is not "configured". Exiting 0 on a pending domain reports
#     success for a site that does not resolve yet.

set -euo pipefail

PENDING_DNS_EXIT_CODE=20

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <resource-group> <static-web-app-name> <custom-domain>"
  echo "Exit code $PENDING_DNS_EXIT_CODE means DNS is not live yet — add the records and re-run."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

require_command az

RESOURCE_GROUP="$1"
STATIC_WEB_APP_NAME="$2"
CUSTOM_DOMAIN="$(lowercase "$3")"

DEFAULT_HOSTNAME="$(az staticwebapp show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$STATIC_WEB_APP_NAME" \
  --query defaultHostname -o tsv)"
[[ -n "$DEFAULT_HOSTNAME" ]] || die "Failed to resolve the default hostname for $STATIC_WEB_APP_NAME"
EXPECTED_TARGET="${DEFAULT_HOSTNAME%.}"

# One label in front of the registrable pair means a subdomain; anything else is apex.
DOT_COUNT="$(printf '%s' "$CUSTOM_DOMAIN" | tr -cd '.' | wc -c | tr -d ' ')"
if [[ "$DOT_COUNT" -le 1 ]]; then
  IS_APEX=1
  VALIDATION_METHOD="dns-txt-token"
  RECORD_NAME="@"
else
  IS_APEX=0
  VALIDATION_METHOD="cname-delegation"
  RECORD_NAME="${CUSTOM_DOMAIN%%.*}"
fi

status_of() {
  az staticwebapp hostname list \
    --resource-group "$RESOURCE_GROUP" --name "$STATIC_WEB_APP_NAME" \
    --query "[?domainName=='$CUSTOM_DOMAIN'].status | [0]" -o tsv 2>/dev/null
}

token_of() {
  az staticwebapp hostname show \
    --resource-group "$RESOURCE_GROUP" --name "$STATIC_WEB_APP_NAME" \
    --hostname "$CUSTOM_DOMAIN" --query validationToken -o tsv 2>/dev/null
}

print_records() {
  local token="${1:-}"
  printf '\nDNS records for %s — every one of them unproxied (grey cloud on Cloudflare):\n\n' \
    "$CUSTOM_DOMAIN"
  if [[ "$IS_APEX" -eq 1 ]]; then
    printf '  TXT    %-6s  %s\n' "$RECORD_NAME" "${token:-<pending: re-run once Azure issues it>}"
    printf '  CNAME  %-6s  %s\n' "$RECORD_NAME" "$EXPECTED_TARGET"
    printf '\n  (Cloudflare flattens a CNAME at the apex automatically. On a provider that\n'
    printf '   cannot, use an A record to the Static Web App inbound IP instead.)\n\n'
  else
    printf '  CNAME  %-6s  %s\n\n' "$RECORD_NAME" "$EXPECTED_TARGET"
  fi
}

dns_ready() {
  command -v dig >/dev/null 2>&1 || return 0          # cannot check; let Azure decide
  if [[ "$IS_APEX" -eq 1 ]]; then
    local token="$1" txt addr
    txt="$(dig +short TXT "$CUSTOM_DOMAIN" | tr -d '"')"
    addr="$(dig +short A "$CUSTOM_DOMAIN"; dig +short CNAME "$CUSTOM_DOMAIN")"
    [[ -n "$token" && "$txt" == *"$token"* ]] || { warn "TXT record for $CUSTOM_DOMAIN not visible yet."; return 1; }
    [[ -n "$addr" ]] || { warn "$CUSTOM_DOMAIN does not resolve to an address yet."; return 1; }
  else
    local observed
    observed="$(dig +short CNAME "$CUSTOM_DOMAIN" | sed 's/\.$//' | head -n 1)"
    [[ -n "$observed" ]] || { warn "No CNAME found for $CUSTOM_DOMAIN yet."; return 1; }
    [[ "$(lowercase "$observed")" == "$(lowercase "$EXPECTED_TARGET")" ]] \
      || { warn "$CUSTOM_DOMAIN points to $observed, not $EXPECTED_TARGET."; return 1; }
  fi
  info "Live DNS looks correct for $CUSTOM_DOMAIN."
}

STATUS="$(status_of)"

if [[ -z "$STATUS" ]]; then
  info "Registering $CUSTOM_DOMAIN by $VALIDATION_METHOD."
  if [[ "$IS_APEX" -eq 0 ]] && ! dns_ready ""; then
    print_records ""
    warn "A subdomain is validated by its CNAME, so publish that record before registering."
    exit "$PENDING_DNS_EXIT_CODE"
  fi
  az staticwebapp hostname set \
    --resource-group "$RESOURCE_GROUP" --name "$STATIC_WEB_APP_NAME" \
    --hostname "$CUSTOM_DOMAIN" --validation-method "$VALIDATION_METHOD" -o none
  STATUS="$(status_of)"
fi

TOKEN=""
[[ "$IS_APEX" -eq 1 ]] && TOKEN="$(token_of)"

case "$STATUS" in
  Ready)
    print_records "$TOKEN"
    info "$CUSTOM_DOMAIN is Ready. https://$CUSTOM_DOMAIN should serve the site."
    exit 0
    ;;
  "")
    die "Azure reported no status for $CUSTOM_DOMAIN after registering it."
    ;;
  *)
    # Validating, Failed, or anything else: not done, and must not report success.
    print_records "$TOKEN"
    info "Azure status: $STATUS"
    if dns_ready "$TOKEN"; then
      info "DNS is in place; Azure polls on its own and usually flips to Ready within minutes."
      info "Re-run this script to check, or: az staticwebapp hostname list -g $RESOURCE_GROUP -n $STATIC_WEB_APP_NAME -o table"
    else
      warn "Publish the records above, then re-run."
    fi
    exit "$PENDING_DNS_EXIT_CODE"
    ;;
esac
