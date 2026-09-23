#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <resource-group> <static-web-app-name> [site-dir]"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

require_command az

REPO_ROOT="$(repo_root)"
RESOURCE_GROUP="$1"
STATIC_WEB_APP_NAME="$2"
SITE_ARG="${3:-site}"
NPX_BIN="$(command -v npx || true)"

if [[ -z "$NPX_BIN" ]]; then
  for candidate in \
    /opt/homebrew/bin/npx \
    /opt/homebrew/opt/node@20/bin/npx \
    /usr/local/bin/npx
  do
    if [[ -x "$candidate" ]]; then
      NPX_BIN="$candidate"
      break
    fi
  done
fi

[[ -n "$NPX_BIN" ]] || die "npx is required"

if [[ "$SITE_ARG" = /* ]]; then
  SITE_DIR="$SITE_ARG"
else
  SITE_DIR="$REPO_ROOT/$SITE_ARG"
fi

[[ -d "$SITE_DIR" ]] || die "Missing site directory: $SITE_DIR"

TOKEN="$(az staticwebapp secrets list \
  --resource-group "$RESOURCE_GROUP" \
  --name "$STATIC_WEB_APP_NAME" \
  --query properties.apiKey \
  -o tsv)"

[[ -n "$TOKEN" ]] || die "Failed to fetch Static Web App deployment token for $STATIC_WEB_APP_NAME"

DEFAULT_HOSTNAME="$(az staticwebapp show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$STATIC_WEB_APP_NAME" \
  --query defaultHostname \
  -o tsv)"

info "Deploying site from $SITE_DIR to $STATIC_WEB_APP_NAME"
"$NPX_BIN" --yes @azure/static-web-apps-cli deploy "$SITE_DIR" \
  --deployment-token "$TOKEN" \
  --env production

info "Frontend deployment complete."
printf 'Default hostname: %s\n' "$DEFAULT_HOSTNAME"
