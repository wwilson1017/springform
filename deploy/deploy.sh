#!/usr/bin/env bash
# Update this server to the image named by IMAGE in .env and wait until it answers.
#
#   sudo /srv/springform/deploy.sh
#
# Deploys are stop-before-start: `docker compose up` stops the old container before it starts
# the new one, because only one process may hold /data/.springform.lock (SQLite has one
# writer). Expect a few seconds of 502 from Caddy during the swap.
set -euo pipefail
cd "$(dirname "$0")"

docker compose pull --quiet
docker compose up -d
docker image prune -f >/dev/null

up='import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/up", timeout=3)'
for _ in $(seq 60); do
  docker compose exec -T app python -c "$up" 2>/dev/null && break
  sleep 2
done
if ! docker compose exec -T app python -c "$up"; then
  docker compose logs --tail 50 app
  echo "Springform did not answer /up within two minutes" >&2
  exit 1
fi
docker compose exec -T app python -c '
import json, urllib.request
health = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=5))
print("Springform", health["version"], "is up (SQLite", health["sqlite_version"] + ")")'
