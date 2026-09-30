#!/usr/bin/env bash
# Add english.bo-bob.com -> http://localhost:3305 to the shared `diet-loggers` cloudflared tunnel
# on this PC, create the DNS route, and restart the tunnel service. Idempotent.
set -euo pipefail
HOST="${1:-english.bo-bob.com}"
PORT="${2:-3305}"
CFG="$HOME/.cloudflared/diet-loggers.yml"
TUNNEL=diet-loggers

if grep -q "hostname: $HOST" "$CFG"; then
  echo "ingress for $HOST already present in $CFG"
else
  cp "$CFG" "$CFG.bak.ehnglish-$(date +%s)"
  # Insert before the catch-all rule (last line of the ingress list).
  python3 - "$CFG" "$HOST" "$PORT" <<'PY'
import sys
cfg, host, port = sys.argv[1], sys.argv[2], sys.argv[3]
lines = open(cfg).read().splitlines(keepends=True)
idx = max(i for i, l in enumerate(lines) if l.strip() == "- service: http_status:404")
indent = lines[idx][: len(lines[idx]) - len(lines[idx].lstrip())]
new = [f"{indent}- hostname: {host}\n", f"{indent}  service: http://localhost:{port}\n"]
lines[idx:idx] = new
open(cfg, "w").write("".join(lines))
print("inserted", host, "->", port)
PY
  cloudflared tunnel --config "$CFG" ingress validate
fi

cloudflared tunnel route dns "$TUNNEL" "$HOST" || echo "(DNS route may already exist)"
systemctl --user restart cloudflared-diet.service
sleep 2
systemctl --user is-active cloudflared-diet.service
echo "done: https://$HOST"
