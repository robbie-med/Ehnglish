#!/usr/bin/env bash
# Thin Cloudflare API wrapper. The token is read from a file and never echoed.
#   CLOUDFLARE_API_TOKEN_FILE  path to a file containing the token (default: ~/Projects/Dad/cloudflare_admin)
# Usage: deploy/cf-api.sh GET  /zones?name=bo-bob.com
#        deploy/cf-api.sh POST /accounts/<id>/access/apps '{"name": ...}'
set -euo pipefail
TOKEN_FILE="${CLOUDFLARE_API_TOKEN_FILE:-$HOME/Projects/Dad/cloudflare_admin}"
method="${1:?method}"; path="${2:?path}"; body="${3:-}"
tok=$(tr -d '\r\n ' < "$TOKEN_FILE" | sed -E 's/^[A-Za-z_]+=//')
args=(-s -X "$method" "https://api.cloudflare.com/client/v4${path}" \
      -H "Authorization: Bearer ${tok}" -H "Content-Type: application/json")
if [[ -n "$body" ]]; then args+=(--data "$body"); fi
curl "${args[@]}"
