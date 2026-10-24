#!/bin/sh
# Starts as root only to give /data to the app user (fresh Docker and Railway volumes are
# root-owned), then runs the one server process as `app`. One worker: SQLite has one writer
# and the backend holds a lock on /data/.springform.lock.
# simplification: chown -R walks /data on every boot, slow past ~100k files; upgrade: chown only
# what `find /data ! -user app` returns.
set -eu
chown -R app:app /data
set -- uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 \
    --timeout-graceful-shutdown 10
# Behind Caddy or Railway's proxy, trust X-Forwarded-* so the app sees https and client IPs.
if [ "${TRUST_PROXY:-0}" = 1 ]; then
    set -- "$@" --proxy-headers --forwarded-allow-ips='*'
fi
exec setpriv --reuid=app --regid=app --init-groups "$@"
