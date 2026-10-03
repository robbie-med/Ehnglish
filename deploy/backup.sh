#!/usr/bin/env bash
# Nightly backup of the raw store and the database (plan §2.6 "keep all raw data", §3 "+R2 backup").
# Writes data/backups/<date>/ with a pg_dump and a tar of data/raw, keeps the last 14, and, if
# `rclone` has a remote called `r2` configured, syncs the backups folder there.
set -euo pipefail
cd "$(dirname "$0")/.."
stamp=$(date +%Y-%m-%d)
out="data/backups/$stamp"
mkdir -p "$out"
docker compose -f deploy/docker-compose.yml exec -T db pg_dump -U ehnglish ehnglish | gzip > "$out/ehnglish.sql.gz"
tar -czf "$out/raw.tar.gz" -C data raw
ls -1dt data/backups/*/ | tail -n +15 | xargs -r rm -rf
if command -v rclone >/dev/null && rclone listremotes | grep -q '^r2:'; then
  rclone sync data/backups r2:ehnglish-backups --fast-list
fi
echo "backup $stamp done: $(du -sh "$out" | cut -f1)"
