#!/usr/bin/env bash

set -euo pipefail

log() {
  local level="$1"
  shift
  printf '%s: %s\n' "$level" "$*" >&2
}

info() {
  log "INFO" "$@"
}

warn() {
  log "WARN" "$@"
}

error() {
  log "ERROR" "$@"
}

die() {
  error "$@"
  exit 1
}

require_command() {
  local command_name="$1"
  command -v "$command_name" >/dev/null 2>&1 || die "$command_name is required"
}

lowercase() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

repo_root() {
  git rev-parse --show-toplevel 2>/dev/null || die "Run this script from inside the sparkly git repository."
}

output_file_path() {
  printf '%s/deploy.outputs.json\n' "$(repo_root)"
}

read_output_value() {
  local file_path="$1"
  local jq_filter="$2"

  [[ -f "$file_path" ]] || die "Missing output file: $file_path"
  jq -er "$jq_filter" "$file_path"
}

normalize_github_https_remote() {
  local owner="$1"
  local repo_name="$2"

  printf 'https://github.com/%s/%s.git\n' "$owner" "$repo_name"
}

remote_matches_expected() {
  local actual_url="$1"
  local owner="$2"
  local repo_name="$3"

  [[ "$actual_url" == "https://github.com/${owner}/${repo_name}" || "$actual_url" == "https://github.com/${owner}/${repo_name}.git" ]]
}

validate_app_name() {
  local app_name="$1"

  [[ "$app_name" =~ ^[a-z0-9-]+$ ]] || die "App name must contain only lowercase letters, numbers, and hyphens: $app_name"
}
