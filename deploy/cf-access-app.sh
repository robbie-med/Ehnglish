#!/usr/bin/env bash
# Create (or show) the Cloudflare Access application for the app, with an allow policy for the
# two login emails. Idempotent: if an app for the domain exists it is printed, not duplicated.
# Uses deploy/cf-api.sh (token from CLOUDFLARE_API_TOKEN_FILE). Prints the AUD for deploy/.env.
set -euo pipefail
cd "$(dirname "$0")"
DOMAIN="${1:-english.bo-bob.com}"
EMAILS="${2:-bgsikora@sikoraweb.com,talk@ruralrobbie.net}"
ACC=$(./cf-api.sh GET "/zones?name=bo-bob.com" | python3 -c "import sys,json; print(json.load(sys.stdin)['result'][0]['account']['id'])")

existing=$(./cf-api.sh GET "/accounts/$ACC/access/apps?per_page=100" | python3 -c "
import sys,json
for a in json.load(sys.stdin)['result']:
    if a.get('domain')=='$DOMAIN': print(a['id'], a['aud']); break")
if [[ -n "$existing" ]]; then
  echo "exists: app_id=${existing% *}"
  echo "EHNGLISH_CF_ACCESS_AUD=${existing#* }"
  exit 0
fi

include=$(python3 -c "
import json; print(json.dumps([{'email': {'email': e.strip()}} for e in '$EMAILS'.split(',') if e.strip()]))")
body=$(python3 -c "
import json
print(json.dumps({
  'name': 'Ehnglish assessment',
  'domain': '$DOMAIN',
  'type': 'self_hosted',
  'session_duration': '720h',
  'auto_redirect_to_identity': False,
  'app_launcher_visible': True,
  'http_only_cookie_attribute': True,
  'policies': [{'name': 'learner + owner', 'decision': 'allow', 'precedence': 1, 'include': $include}],
}))")
resp=$(./cf-api.sh POST "/accounts/$ACC/access/apps" "$body")
echo "$resp" | python3 -c "
import sys,json
d=json.load(sys.stdin)
if not d.get('success'):
    print('ERROR', d.get('errors')); sys.exit(1)
r=d['result']; print('created: app_id='+r['id']); print('EHNGLISH_CF_ACCESS_AUD='+r['aud'])"
