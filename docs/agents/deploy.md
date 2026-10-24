# Deploy, backups and restore

**What this covers:** §13's Dockerfile and entrypoint, `/up` vs `/api/health`, the `deploy/` files, `setup.sh`, `deploy.sh`, Railway, stop-before-start, the `TRUST_PROXY` constraint, and (from §1) the encryption key, backups as recovery sets, off-site copies and `scripts/restore.sh`.
**Who reads it:** W8 (Dockerfile, `deploy/`, scripts, release, image test), W3 (backup + restore test, Backups page), and anyone deploying an install.

## 1. Dockerfile

| Stage | Contract |
|---|---|
| `sqlite` | Builds the **SQLite 3.51.3 amalgamation, SHA-pinned**. |
| `frontend` | `node:22-slim`. **Copies `backend/apps`** so `vite-plugin-apps.ts` sees every `app.json`. Builds the frontend. |
| runtime | `python:3.12-slim` + uv (`uv sync --frozen --no-dev`); `COPY --from=sqlite libsqlite3.so.0*`; `tzdata`; a non-root `app` user **but no `USER` line**. |

Runtime image settings: `VOLUME /data`, `HEALTHCHECK` on `/up`, `STOPSIGNAL SIGTERM`.

## 2. `entrypoint.sh`

1. Starts as **root**.
2. `chown -R app /data` (Railway and fresh volumes are root-owned).
3. `exec setpriv --reuid=app --regid=app --init-groups uvicorn --workers 1 --timeout-graceful-shutdown 10`.
4. With `TRUST_PROXY=1`, uvicorn also gets `--proxy-headers --forwarded-allow-ips='*'`.

Open: the uvicorn app target (`run.py` is in the repo root; its role is not stated) and the bind address and port (the Caddyfile proxies to `app:8000`) are not stated.

## 3. Health endpoints

| Route | Auth | Contract |
|---|---|---|
| `GET /up` | none | Runs `SELECT 1`, returns `200 "ok"`. Docker `HEALTHCHECK`, `deploy.sh` and Railway use it. |
| `GET /api/health` | none | `{version, sqlite_version, fts5, preview, apps:[slug], last_backup_at}`. `version` from `springform-version`. |

The **CI image test** runs the container and asserts `/api/health` reports `sqlite_version >= 3.51.3` and `fts5: true`.

## 4. `deploy/`

| File | Contract |
|---|---|
| `compose.yml` | The app service, bound **only on the compose network** (its port is never published), plus `caddy:2` publishing 80/443. Image from `IMAGE=` in `.env` (default: the fork's own image; `forks.md`). |
| `Caddyfile` | `{$DOMAIN} { reverse_proxy app:8000 }` (automatic HTTPS). |
| `.env.example` | The environment template (`setup.sh` generates `.env`). |
| `setup.sh` | Fresh VPS bootstrap (below). |
| `deploy.sh` | Update an install (below). |

`railway.json` (repo root, optional): healthcheck `/up`, `requiredMountPath /data`; `RAILWAY_DEPLOYMENT_DRAINING_SECONDS=15` documented.

### `TRUST_PROXY` constraint

With `TRUST_PROXY=1` the app port is bound only on the compose network, never published, so forwarded headers can only come from Caddy. `compose.yml` enforces it. Cookie `secure=` follows the real scheme; startup warns if `PUBLIC_URL` is https but requests are not (`auth.md` §8).

### `setup.sh` (Ubuntu 24.04)

1. Install Docker + the compose plugin, **pinned**.
2. Create `/srv/springform/{data,backups}`.
3. Write `.env` with generated secrets and a `DOMAIN` prompt.
4. ufw: allow 22, 80, 443.
5. Enable unattended-upgrades.
6. `compose up -d`.
7. Print the **setup token** (`auth.md` §5).
8. Offer the rclone off-site cron (§7 below).

Open: `setup.sh` creates `/srv/springform/backups`, while backups are written inside the container to `/data/backups`; whether the host `backups` directory is a separate mount or the off-site staging area is not stated. Open: which "generated secrets" `.env` holds (at least `ENCRYPTION_KEY`; a JWT secret if one is env-sourced).

### `deploy.sh`

1. `docker compose pull`.
2. `compose up` (which **stops the old container first**).
3. Prune old images.
4. Wait on `/up`.
5. Print the version.

## 5. Stop-before-start

The single-process `flock` on `/data/.springform.lock` (`database-and-transactions.md` §9) means two containers can never serve the same volume. Deploys are stop-before-start:

1. compose recreate stops the old container before starting the new one;
2. Railway stops the old container before starting the new one on a volume, which the `flock` relies on.

## 6. Encryption key

Lifted from CakeCRM `core/secret_store.py` (minus keychain) and `core/encryption.py` (`enc:v1:` format).

1. Fernet key from env `ENCRYPTION_KEY` → else `/data/.encryption-key` → else generated on first boot into that file.
2. When `ENCRYPTION_KEY` comes from the environment, no key file exists, and the Backups page says "your key is in your environment; keep it with your `.env`".
3. Otherwise the Backups page shows the key **once**, with "store this off-site; without it a restored copy cannot read stored credentials".

## 7. Backups: recovery sets

**Backup = the `/data` volume, as recovery sets.** `backend/core/backup.py` adapts todo-gtd `backend/backup.py`.

### The job (`core.backup`, 03:00 install-local)

1. `VACUUM INTO` a `.tmp` file, then `os.replace` into `/data/backups/<stamp>.sqlite`.
2. Write `/data/backups/<stamp>.manifest.json` **last**, containing:
   - the snapshot filename and its sha256;
   - the list of blob sha256s referenced by `core_files` at snapshot time;
   - the encryption-key fingerprint;
   - the Springform version.
3. Keep the newest **7** sets.
4. Pause when free space is under **100 MB**.
5. Never raise.
6. Log to `core_backups`.
7. "Back up now" on the Backups page runs the same job.

### Blob pinning

**A blob is never deleted while any retained manifest lists it.** The file sweep reads the manifests (`records.md` §2), so every retained set restores whole. Pruning a set is what releases its blobs.

### Off-site

`deploy/setup.sh` offers an rclone cron that copies, **in order**: blobs → snapshot → manifest (so a remote set is complete when its manifest is present), and `/data/.encryption-key` if it exists.

Open: the `<stamp>` format, the `core_backups` columns, and the Backups page's download route are not stated.

## 8. `scripts/restore.sh`

```
scripts/restore.sh <manifest>
```

1. Verifies the set (snapshot sha256, every listed blob present).
2. Copies it into an **empty** `/data`.
3. Checks the key fingerprint. A wrong key fails loudly ("wrong key") instead of returning garbage.

### Restore test (CI)

1. Take a snapshot.
2. Restore the set into an empty volume, with the key.
3. Boot, open an attachment, decrypt a stored provider key.
4. A second test restores with the **wrong key** and must fail before serving.

Litestream is deferred ("later").

## Tests that pin this

- CI image test: `/api/health` reports `sqlite_version >= 3.51.3` and `fts5: true`.
- Restore test: snapshot + files + key → empty volume → attachment opens, credential decrypts; wrong key fails before serving.
- A fresh blob survives `sweep`; an unreferenced blob survives 6 days and goes at 8.
- Playwright: Back up now creates a file.
- Live: Multipass Ubuntu 24.04 VM dry run (`setup.sh` with `DOMAIN=localhost`, `/up`, `deploy.sh` to a second tag, restore drill into an empty volume); Railway preview with the root-owned volume.

## Source

Build plan: §13 (Dockerfile, `deploy/`, Railway), §1 (secrets, backups, restore), §2 (proxy), SQLite rules (single process, SQLite version), Decisions (Ops, Hosting), Step 5, Verification.
