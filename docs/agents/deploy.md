# Deploy, backups and restore

**What this covers:** §13's Dockerfile and entrypoint, `/up` vs `/api/health`, the `deploy/` files, `setup.sh`, `deploy.sh`, Railway, stop-before-start, the `TRUST_PROXY` constraint, and (from §1) the encryption key, backups as recovery sets, off-site copies and `scripts/restore.sh`.
**Who reads it:** W8 (Dockerfile, `deploy/`, scripts, release, image test), W3 (backup + restore test, Backups page), and anyone deploying an install.

## 1. Dockerfile

| Stage | Contract |
|---|---|
| `sqlite` | Builds the **SQLite 3.51.3 amalgamation, SHA-pinned**. |
| `frontend` | `node:22-slim`. **Copies `backend/apps`** so `vite-plugin-apps.ts` sees every `app.json`. Builds the frontend. |
| runtime | `python:3.12-slim` + uv (`uv sync --frozen --no-dev --no-install-project`); `COPY --from=sqlite libsqlite3.so.0*`; the base image's tzdata (`scripts/check-sqlite.py` checks SQLite, FTS5 and zoneinfo at build time); a non-root `app` user **but no `USER` line**. The image sets `DATA_DIR=/data` and `SPRINGFORM_REQUIRE_SQLITE=1`. |

Runtime image settings: `VOLUME /data`, `HEALTHCHECK` on `/up`, `STOPSIGNAL SIGTERM`.

## 2. `entrypoint.sh`

1. Starts as **root**.
2. `chown -R app /data` (Railway and fresh volumes are root-owned).
3. `exec setpriv --reuid=app --regid=app --init-groups uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --timeout-graceful-shutdown 10`.
4. With `TRUST_PROXY=1`, uvicorn also gets `--proxy-headers --forwarded-allow-ips='*'`.
5. `run.py` at the repo root is the dev runner only; the image never uses it.

## 3. Health endpoints

| Route | Auth | Contract |
|---|---|---|
| `GET /up` | none | Runs `SELECT 1`, returns `200 "ok"`. Docker `HEALTHCHECK`, `deploy.sh` and Railway use it. |
| `GET /api/health` | none | `{version, sqlite_version, fts5, preview, apps:[slug], last_backup_at, key_mismatch}`. `version` from `springform-version`, which must be a PEP 440 version (`0.1.0`, `0.1.0+fork.1`): startup checks each app's `requires_core` against it, and a string like `0.1.0-fork` stops the boot with a message naming the file and the value. |

The **CI image test** runs the container and asserts `/api/health` reports `sqlite_version >= 3.51.3` and `fts5: true`.

## 4. `deploy/`

| File | Contract |
|---|---|
| `compose.yml` | The app service with `/srv/springform/data` mounted at `/data`, bound **only on the compose network** (its port is never published), plus `caddy:2` publishing 80/443. Image from `IMAGE=` in `.env`, default the upstream `ghcr.io/wwilson1017/springform:latest`; a fork sets its own (`setup.sh` takes `IMAGE=`; `forks.md`). |
| `Caddyfile` | `{$DOMAIN} { reverse_proxy app:{$PORT:8000} }` (automatic HTTPS); compose passes `PORT` from `.env` to the caddy service. |
| `.env.example` | The environment template (`setup.sh` generates `.env`). |
| `setup.sh` | Fresh VPS bootstrap (below). |
| `deploy.sh` | Update an install (below). |
| `offsite.sh` | The off-site copy the cron runs (§7). |

`railway.json` (repo root, optional): builds the repo's own `Dockerfile` (it never reads `IMAGE`), healthcheck `/up`, `requiredMountPath /data`; `RAILWAY_DEPLOYMENT_DRAINING_SECONDS=15` documented.

### `TRUST_PROXY` constraint

With `TRUST_PROXY=1` the app port is bound only on the compose network, never published, so forwarded headers can only come from Caddy. `compose.yml` enforces it. Cookie `secure=` follows the real scheme; startup warns if `PUBLIC_URL` is https but requests are not (`auth.md` §8).

### `setup.sh` (Ubuntu 24.04)

1. Install Docker and the compose plugin from Docker's apt repository. The packages are unversioned; the repository's GPG key fingerprint is pinned.
2. Create `/srv/springform/data`, which `compose.yml` mounts at `/data`. No other host directory is created; backups live inside it.
3. Write `.env` with `DOMAIN` (prompted, or from `DOMAIN=`), `IMAGE`, `PUBLIC_URL=https://<domain>`, a generated `SECRET_KEY` and `ENCRYPTION_KEY`, and empty `RESEND_API_KEY` / `MAIL_FROM`.
4. ufw: allow 22, 80, 443.
5. Enable unattended-upgrades.
6. Start through `deploy.sh`.
7. Offer the rclone off-site cron (§7 below); `RCLONE_REMOTE=` sets it up unattended.
8. Print the **setup token** (`auth.md` §5).

Re-running it is safe: it keeps an existing `.env`, adds no duplicate ufw rule or cron, and leaves running containers alone. Because `.env` is kept, `DOMAIN=` and `IMAGE=` count only on the first run; later, edit `.env`.

`NO_PULL=1` runs an `IMAGE` loaded with `docker load` instead of pulling it, for a dry run before an image is published or a server without registry access. Docker does not exist before the first run, so on a fresh server that run installs it and stops with "not loaded"; load the image and run `setup.sh` again:

```bash
docker save springform:test | gzip > springform-test.tar.gz      # on the build machine
sudo DOMAIN=localhost IMAGE=springform:test NO_PULL=1 deploy/setup.sh   # on the server: installs Docker, stops
sudo docker load -i springform-test.tar.gz && sudo DOMAIN=localhost IMAGE=springform:test NO_PULL=1 deploy/setup.sh
```

`DOMAIN=localhost` gets a certificate from Caddy's internal CA, so test with `curl -k https://localhost/up`. API calls made with curl and a session cookie need `-H 'Sec-Fetch-Site: same-origin'`, as a browser sends (`auth.md`, CSRF).

### `deploy.sh`

1. `docker compose pull`; with `NO_PULL=1`, skipped, and the app image must already be loaded.
2. `compose up` (which **stops the old container first**).
3. Prune dangling images (a replaced `:latest`; a pinned tag stays until removed by hand).
4. Wait on `/up`.
5. Print the version.

To move to another release, set `IMAGE` in `.env`, then run `deploy.sh`. An `IMAGE=` given on the command line also works, because compose prefers the shell's value, but the next plain `deploy.sh` goes back to the `.env` one. Expect about ten seconds of 502 from Caddy: the old container stops in about two, and the new one needs most of the rest to boot.

## 5. Stop-before-start

The single-process `flock` on `/data/.springform.lock` (`database-and-transactions.md` §9) means two containers can never serve the same volume. Deploys are stop-before-start:

1. compose recreate stops the old container before starting the new one;
2. Railway stops the old container before starting the new one on a volume, which the `flock` relies on.

## 6. Encryption key

Lifted from CakeCRM `core/secret_store.py` (minus keychain) and `core/encryption.py` (`enc:v1:` format).

1. Fernet key from env `ENCRYPTION_KEY` → else `/data/.encryption-key` → else generated on first boot into that file.
2. When `ENCRYPTION_KEY` comes from the environment, no key file exists. `POST /api/core/backups/key` then returns only `{key_source: "env", fingerprint}`, and the Backups page says to keep the key with the `.env`.
3. Otherwise `POST /api/core/backups/key` (admin) returns `{key_source: "file", key, fingerprint}` **once**. Every later call answers **410** `key_already_shown`. The Backups page tells the admin to store the key off-site, because without it a restored copy cannot read stored credentials.

## 7. Backups: recovery sets

**Backup = the `/data` volume, as recovery sets.** Sets are written inside the container to `/data/backups` (on the host, `/srv/springform/data/backups`). The `backend/core/backup/` package (`service.py`, `restore.py`, `jobs.py`, `router.py`) adapts todo-gtd `backend/backup.py` in `service.py`.

### The job (`core.backup`, 03:00 install-local)

1. `VACUUM INTO` a `.tmp` file, then `os.replace` into `/data/backups/<stamp>.sqlite`. `<stamp>` is `YYYYMMDDTHHMMSSZ`; a second set in the same second (a frozen clock, a double click) is `-2`, `-3`, …, and retention sorts the numbers as numbers.
2. Write `/data/backups/<stamp>.manifest.json` **last**, containing:
   - the snapshot filename and its sha256;
   - the list of blob sha256s referenced by `core_files` at snapshot time;
   - the encryption-key fingerprint;
   - the Springform version.
3. Keep the newest **7** sets.
4. Skip the run, recorded as `skipped` in `core_backups`, when free space is below the database file's size plus **100 MB**.
5. Never raise.
6. Log to `core_backups`.
7. "Back up now" is `POST /api/core/backups/run` (admin). It calls the backup service directly, under the same guard as the job, and returns **202** with the `core_backups` row, or **409** `backup_in_progress`. It writes no `core_job_runs` row; its outcome is the `core_backups` row.

```sql
core_backups(id, started_at, finished_at, status CHECK (status IN ('running','ok','error','skipped')),
             snapshot, manifest, byte_size, sha256, error)
```

Backups API (admin only):

```
GET  /api/core/backups                    -> {sets, last_backup_at, last_run, key_source, key_shown, key_mismatch}
POST /api/core/backups/run                -> 202 the core_backups row; 409 backup_in_progress
POST /api/core/backups/key                -> {key_source, key?, fingerprint}; 410 key_already_shown
GET  /api/core/backups/{stamp}/download   -> the snapshot file
GET  /api/core/backups/{stamp}/manifest   -> the manifest JSON
```

### Blob pinning

**A blob is never deleted while any retained manifest lists it.** The file sweep reads the manifests (`records.md` §2), so every retained set restores whole. Pruning a set is what releases its blobs.

### Off-site

`deploy/setup.sh` offers a nightly cron on the host, at 04:00 server time, that runs `deploy/offsite.sh <rclone-remote:path>`. Each run copies the newest set from `/srv/springform/data/backups`, **in order**: the whole `files/` directory, then the snapshot, then its manifest (so a remote set is complete when its manifest is present), then the volume's `.encryption-key` if it exists. The remote keeps every set and blob (a marked simplification).

## 8. `scripts/restore.sh`

```
scripts/restore.sh <manifest> <empty_target_data_dir> [--files-from <source_data_dir>] [--key-file <path>] [--allow-missing-blobs]
```

It wraps `python -m backend.core.backup.restore`. Every check runs before anything is written:

1. Verifies the set: the manifest, the snapshot's sha256, and every listed blob present with the right sha256. Blobs are read from `<files-from>/files/`, or by default from the data directory that holds the manifest's `backups/` folder. `--allow-missing-blobs` restores even when some are missing.
2. Requires the target data directory to be **empty**, then copies the set into it.
3. Checks that the key the restored install will use has the manifest's fingerprint. That key is `ENCRYPTION_KEY` when set, and the `--key-file` when given. A wrong key fails loudly instead of booting an install that cannot read its stored credentials.

Exit codes: 0 restored, 1 refused or failed, 2 usage.

`scripts/restore.sh` needs a checkout and `uv`. A server set up by `setup.sh` has neither, so run the same module inside the app image. With the `ENCRYPTION_KEY` from `.env` (compose passes it), the old data directory mounted read-only, and the new empty one as `/data`:

```bash
cd /srv/springform
sudo docker compose stop app
sudo mv -T data data.before-restore && sudo mkdir data   # -T: refuses if an older one is still there
sudo docker compose run --rm --no-deps -v "$PWD/data.before-restore:/restore-from:ro" --entrypoint python app \
  -m backend.core.backup.restore /restore-from/backups/<stamp>.manifest.json /data
sudo docker compose up -d app        # entrypoint.sh gives the restored files to the app user
```

If the restore refuses, `data/` is still empty: `sudo rmdir data && sudo mv data.before-restore data` puts the old one back. Restoring from the off-site copy works the same way: `rclone copy <remote:path> <dir>` gives `<dir>/backups/` and `<dir>/files/`, so mount `<dir>` as `/restore-from`. On a new server, first put the old `.env`'s `ENCRYPTION_KEY` and `SECRET_KEY` into the new `.env`: `setup.sh` generated fresh ones, and the restore refuses the new key.

Only the restore refuses a wrong key. A data directory copied by hand boots with a wrong `ENCRYPTION_KEY` and serves: every stored credential then reads as unset (the Whisk provider shows a key but "not configured"). The boot does notice: `backup/startup.py` compares the key's fingerprint with the newest manifest under `/data/backups`, and on a mismatch logs an ERROR with the remedy and stores the manifest's filename in the internal `core_settings` row `backups.key_mismatch` (cleared on the next boot that matches, or when there is no backup). It never refuses to boot, so an install whose key is lost can still be recovered. The Backups overview (`GET /api/core/backups`, admin only) returns that filename as `key_mismatch` (null when the keys match), and the public `/api/health` reports only `key_mismatch: true` or `false`. So restore through the module, never by copying files.

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
