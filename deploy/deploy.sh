#!/usr/bin/env bash
# Update this server to the image named by IMAGE in .env and wait until it answers.
#
#   sudo /srv/springform/deploy.sh
#   sudo NO_PULL=1 /srv/springform/deploy.sh   # run an IMAGE already loaded with `docker load`
#
# Deploys are stop-before-start: `docker compose up` stops the old container before it starts
# the new one, because only one process may hold /data/.springform.lock (SQLite has one
# writer). Expect about ten seconds of 502 from Caddy while the new container boots.
set -euo pipefail
cd "$(dirname "$0")"

# NO_PULL=1 skips the registry for the app image; compose still fetches Caddy on a first run.
if [ "${NO_PULL:-0}" = 1 ]; then
  image=$(docker compose config --images app)
  docker image inspect "$image" >/dev/null 2>&1 || {
    echo "NO_PULL=1 but $image is not loaded here: run 'docker load -i <file>', then this again" >&2
    exit 1
  }
else
  docker compose pull --quiet
fi
docker compose up -d
docker image prune -f >/dev/null

base='import os, urllib.request; base = "http://127.0.0.1:%s" % os.environ.get("PORT", "8000")'
up="$base"'; urllib.request.urlopen(base + "/up", timeout=3)'
for _ in $(seq 60); do
  docker compose exec -T app python -c "$up" 2>/dev/null && break
  sleep 2
done
if ! docker compose exec -T app python -c "$up"; then
  docker compose logs --tail 50 app
  echo "Springform did not answer /up within two minutes" >&2
  exit 1
fi
docker compose exec -T app python -c "$base"'
import json
health = json.load(urllib.request.urlopen(base + "/api/health", timeout=5))
print("Springform", health["version"], "is up (SQLite", health["sqlite_version"] + ")")'
