# Deploy, backups and restore

**What this covers:** §13's Dockerfile and entrypoint, `/up` vs `/api/health`, the `deploy/` files, `setup.sh`, `deploy.sh`, Railway, stop-before-start, the `TRUST_PROXY` constraint, and (from §1) the encryption key, backups as recovery sets, off-site copies and `scripts/restore.sh`; releases (`release.yml`).
**Who reads it:** W8 (Dockerfile, `deploy/`, scripts, release, image test), W3 (backup + restore test, Backups page), and anyone deploying an install.

## 1. Dockerfile

| Stage | Contract |
|---|---|
| `sqlite` | Builds the **SQLite 3.51.3 amalgamation, SHA-pinned**. |
| `frontend` | `node:22-slim`. **Copies `backend/apps`** so `vite-plugin-apps.ts` sees every `app.json`. Builds the frontend. |
| runtime | `python:3.12-slim` + uv (`uv sync --frozen --no-dev --no-install-project`); `COPY --from=sqlite libsqlite3.so.0*`; the base image's tzdata (`scripts/check-sqlite.py` checks SQLite, FTS5 and zoneinfo at build time); a non-root `app` user **but no `USER` line**. The image sets `DATA_DIR=/data` and `SPRINGFORM_REQUIRE_SQLITE=1`. |

Runtime image settings: `HEALTHCHECK` on `/up`, `STOPSIGNAL SIGTERM`. There is deliberately no `VOLUME /data`: Railway refuses to build a Dockerfile that declares one, and every supported run (compose, `docker run -v`, a Railway volume) mounts `/data` itself. A run without a mount keeps its data in the container and loses it on the next deploy.

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
| `Caddyfile` | `{$DOMAIN} { reverse_proxy app:{$PORT:8000} }` (automatic HTTPS) with `header_up X-Real-IP {remote_host}`, the client address the rate limits count (`auth.md` §8); compose passes `PORT` from `.env` to the caddy service. |
| `.env.example` | The environment template (`setup.sh` generates `.env`). |
| `setup.sh` | Fresh VPS bootstrap (below). |
| `deploy.sh` | Update an install (below). |
| `offsite.sh` | The off-site copy the cron runs (§7). |

### Railway

`.railway/railway.ts` stores the Dockerfile build (`Dockerfile`, never `IMAGE`), `/up`
health check (60 s) and 3 restart retries on the service; restart on failure is Railway's
default. Railway never reads it during a deploy. It starts from the live service to
preserve its source, variables and attached volumes; `SPRINGFORM_SERVICE` selects the service.

Create the service and attach its `/data` volume first. Nothing checks for it: Railway
stores no required mount path, so a service without the volume deploys and loses its data on
the next deploy. From a checkout linked with
`railway link` to that project and environment, using Node 22.6+ (the CLI evaluates
TypeScript with `--experimental-strip-types`; tested with Railway CLI 5.54.1):

```bash
SPRINGFORM_SERVICE=<service> railway config plan
# Read every changed field: expect only the build/deploy settings above, nothing deleted.
SPRINGFORM_SERVICE=<service> railway config apply
```

Apply once per service in each environment, and again whenever an upstream update changes
this file. A plan after an apply shows no changes. Set `RAILWAY_DEPLOYMENT_DRAINING_SECONDS=15`
for graceful shutdown.

If plan stops because the service is still managed by Config as Code (a service whose Settings
name a Config File path), clear that path in the service's Settings, as Railway's migration
guide says, and plan again. Do not use `railway config migrate --apply`: applying the file it
writes deletes the service's variables and detaches its volume.

### `TRUST_PROXY` constraint

With `TRUST_PROXY=1` the app port is bound only on the compose network, never published, so forwarded headers can only come from Caddy. `compose.yml` enforces it. Cookie `secure=` follows the real scheme; startup warns if `PUBLIC_URL` is https but requests are not (`auth.md` §8).

### Security headers

The app sets these defaults on every HTTP response, including errors and CSRF refusals,
so Caddy, Railway and bare Docker installs all receive them without proxy header configuration.
`backend/core/security_headers.py` wraps the whole built middleware stack, including the
server error handler. A route's own header value wins.

| Header | Value |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `SAMEORIGIN` |
| `Content-Security-Policy` | `frame-ancestors 'self'` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Strict-Transport-Security` | `max-age=31536000` (HTTPS only) |

Same-origin framing stays allowed for in-app previews. HSTS is added only when the request
scheme is HTTPS; behind Caddy or Railway's proxy this needs `TRUST_PROXY=1` so uvicorn trusts
`X-Forwarded-Proto`. Plain HTTP gets no HSTS default. There is no `includeSubDomains` or
`preload`: an install may sit on a subdomain without controlling the parent domain or other
subdomains. A script/style CSP is deliberately deferred because `frontend/index.html` has an
inline theme script that needs its own design.

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
   - the list of blob sha256s referenced by the blob holders (`core_files`, `core_agent_uploads`) at snapshot time;
   - the encryption-key fingerprint;
   - the Springform version.
3. Keep the newest **7** sets. Before the manifest, `PRAGMA quick_check` runs on the snapshot. A snapshot that fails it is an `error` run, never a set, and is never uploaded.
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
GET    /api/core/backups                    -> {sets, last_backup_at, last_run, key_source, key_shown, key_mismatch, offsite}
POST   /api/core/backups/run                -> 202 the core_backups row (after the off-site copy); 409 backup_in_progress
POST   /api/core/backups/key                -> {key_source, key?, fingerprint}; 410 key_already_shown
GET    /api/core/backups/{stamp}/download   -> the snapshot; with a passphrase <stamp>.sqlite.age; 409 offsite_config_unreadable
GET    /api/core/backups/{stamp}/manifest   -> the manifest JSON
PUT    /api/core/backups/destination        {endpoint, bucket, region="us-east-1", prefix="", access_key_id, secret_key?, retention=30} -> offsite
DELETE /api/core/backups/destination        -> offsite (the passphrase stays)
POST   /api/core/backups/destination/test   -> {ok: true}; 502 with the storage service's refusal
PUT    /api/core/backups/passphrase         {passphrase (8+ chars)} -> offsite
DELETE /api/core/backups/passphrase         -> offsite
```

`offsite` is `{configured, unreadable, endpoint, bucket, region, prefix, access_key_id, retention, encrypted, last_success_at, last_success_bytes, last_error, stale}`. It never holds the secret or the passphrase. `stale` is true when a destination is set and there has been no good upload in 48 hours, counted from when the destination was saved if there has never been one.

### Blob pinning

**A blob is never deleted while any retained manifest lists it.** The file sweep reads the manifests (`records.md` §2), so every retained set restores whole. Pruning a set is what releases its blobs.

### Off-site, in the app (`backup/offsite.py`)

An admin sets an S3-compatible bucket on the Backups page. Any provider works: AWS S3, Cloudflare R2 (region `auto`), Backblaze B2, MinIO. The client (`backup/s3.py`) signs its own SigV4 PUT, GET, DELETE and LIST requests, with no SDK.

1. **When.** `service.run` calls `offsite.upload` under the same guard after every good set, outside any transaction, so both the 03:00 job and "Back up now" upload.
   - Back up now waits for the upload inside its request (a marked simplification).
   - The job's timeout is 3600 s, and it checks its cancel event between objects, prune included.
   - An interrupted copy resumes on the next run, because blobs already in the bucket are skipped.
2. **Layout.** The bucket mirrors the volume, so a downloaded copy restores with `restore.py` unchanged. Objects go up **in this order**: `<prefix>files/<aa>/<sha>`, then `<prefix>backups/<stamp>.sqlite`, then `<prefix>backups/<stamp>.manifest.json`. A remote set is complete once its manifest is there. Blobs are content-addressed and uploaded once.
3. **Missing or damaged blobs.** Each blob not yet in the bucket is hashed before upload. The copy stops before the snapshot when the manifest lists a blob that is neither in the bucket nor on this volume with its SHA-256 matching its name. Nothing is published, nothing is pruned, and the error is recorded, so a set that restore would refuse never reaches the bucket.
4. **Passphrase.** With a backup passphrase, every object is age-encrypted (scrypt recipient, `backup/age.py`) and ends in `.age`, the manifest included.
   - Encrypted objects go under their own root, `<prefix>age-<generation>/`, with the same layout inside.
   - Every `PUT /passphrase` starts a new random generation. A changed passphrase therefore never overwrites an attachment that an older retained set, encrypted with the old passphrase, still needs.
   - The download route encrypts too, serving `<stamp>.sqlite.age` from a temporary file that is deleted after the response. It ignores `Range` (`Accept-Ranges: none`): every download is a fresh ciphertext, so a resumed tail would not decrypt. The plain download still resumes.
   - Sets on the volume stay plain, because restore reads them.
5. **Prune.** It works from the bucket's own listing, never from local state. It keeps the newest `retention` complete sets across every root and deletes the objects of all the others, manifest first. Then, per root:
   - **A root with no retained set** loses all its blobs.
   - **The plain root and the current generation's root** keep only the blobs their retained manifests list. Each manifest is read back, decrypted and validated; one that is unreadable or malformed leaves that root's blobs alone (fail closed) and is recorded as the last error once the rest is pruned.
   - **An older generation's root with a retained set** keeps every blob until its sets age out, because its passphrase is no longer known.

   Only stamp-shaped and blob-shaped names are ever deleted, classified by their suffix after the prefix. Before each deletion the run re-reads the config row and stops if it changed (the admin removed the destination or changed retention mid-run).
   - **Versioned buckets** (Backblaze B2 keeps every version by default; S3 and R2 with versioning on) turn a delete into a hidden version that is still stored and billed. Add a lifecycle rule on the prefix that expires noncurrent versions, e.g. B2's "Keep only the last version of the file" (`daysFromHidingToDeleting: 1`).
6. **Never the key.** The upload touches only `files/` and `backups/`. `.encryption-key` and `ENCRYPTION_KEY` never go to the bucket: keep the key apart from it.
7. **Storage.** The destination, its secret and the passphrase are one secret `core_settings` row, `backups.offsite_config`. Outcomes go to the plain row `backups.offsite`, and a run records its outcome only if the config is unchanged since it started.
   - When the install key cannot decrypt the config row, it is reported as `unreadable`, never taken for "no passphrase".
   - The upload is then skipped and the download answers 409.
   - The page and the banner say to set the destination again.
8. **Visibility.** The Backups page shows the last good upload (time and size) and the last error. For admins, `OffsiteWarning` in the Layout shows a banner on every page when the copy is stale, failing or unreadable.

Simplifications:

- One PUT per object, so about 5 GB at most per object. Upgrade path: CakeCRM's multipart `put_file`.
- One scrypt per encrypted object at age's work factor 18, about a second each, so a first encrypted copy of many attachments is slow.
- Retained remote manifests are read again on every prune.

### Off-site, on the host (rclone)

The in-app copy replaces this for most installs. If both run, retire the cron (`sudo crontab -e`) or point it at another bucket or prefix. `offsite.sh` copies `.encryption-key` next to the sets, so it must never write into the app's prefix. Delete any key file it already left there.

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

### Restoring from the bucket (in-app off-site copy)

The backup does not hold the encryption key. Use the key you kept apart, or `ENCRYPTION_KEY` from the old `.env`.

1. **Fetch** the root that holds the set into one directory, with any S3 tool: `<prefix>` for a plain set, `<prefix>age-<generation>/` for an encrypted one. For example, `rclone copy r2:bucket/<root> ./pulled` gives `./pulled/backups/` and `./pulled/files/`.
2. **Decrypt** an encrypted set with [age](https://age-encryption.org) (`apt install age`) and the passphrase alone. Each `x.age` becomes `x` beside it, and the `.age` files can stay. age asks for the passphrase once per file:
   ```bash
   find ./pulled -name '*.age' -exec sh -c 'age -d -o "${1%.age}" "$1"' _ {} \;
   ```
   For many attachments, one pass with pyrage (`pip install pyrage`) asks once:
   ```bash
   read -rs PASS; export PASS
   python3 -c 'import os, pathlib, pyrage
   for p in pathlib.Path("pulled").rglob("*.age"): p.with_suffix("").write_bytes(pyrage.passphrase.decrypt(p.read_bytes(), os.environ["PASS"]))'
   ```
3. **Restore** with the module as above, mounting `./pulled` as `/restore-from`: `-m backend.core.backup.restore /restore-from/backups/<stamp>.manifest.json /data`, with `--key-file` unless `ENCRYPTION_KEY` is set.
4. **Keep a drill copy away from the production bucket.** The restored database holds the destination, and its 03:00 job would upload into the production prefix and prune it. Before a drill copy's first boot, remove the setting:
   ```bash
   sqlite3 <target>/springform.sqlite "DELETE FROM core_settings WHERE key IN ('backups.offsite_config', 'backups.offsite')"
   ```
   A real restore onto a new server keeps the destination.

Only the restore refuses a wrong key. A data directory copied by hand boots with a wrong `ENCRYPTION_KEY` and serves: every stored credential then reads as unset (the Whisk provider shows a key but "not configured"). The boot does notice: `backup/startup.py` compares the key's fingerprint with the newest manifest under `/data/backups`, and on a mismatch logs an ERROR with the remedy and stores the manifest's filename in the internal `core_settings` row `backups.key_mismatch` (cleared on the next boot that matches, or when there is no backup). It never refuses to boot, so an install whose key is lost can still be recovered. The Backups overview (`GET /api/core/backups`, admin only) returns that filename as `key_mismatch` (null when the keys match), and the public `/api/health` reports only `key_mismatch: true` or `false`. So restore through the module, never by copying files.

### Restore test (CI)

1. Take a snapshot.
2. Restore the set into an empty volume, with the key.
3. Boot, open an attachment, decrypt a stored provider key.
4. A second test restores with the **wrong key** and must fail before serving.

Litestream is deferred ("later").

## 9. Releases (`release.yml`)

1. **Gate.** A `v*` tag runs `release.yml`, which first calls the whole of `ci.yml` (`on: workflow_call`): every job in it must pass on the tagged commit before anything is pushed. There is one definition of the checks; on pull requests and `master` the jobs keep their plain names, so the required checks are unchanged.
2. **Tags.** Every tag publishes `ghcr.io/<repository, lowercased>:<tag>`. Only a tag without a hyphen (`v0.1.0`) also moves `:latest`, the image `deploy/compose.yml` runs by default. A pre-release (`v0.2.0-rc1`) publishes only its own tag. The tag must equal `v` + `springform-version` (`0.1.1-rc1` in the file for a `v0.1.1-rc1` tag); a mismatched tag fails the `Tag matches springform-version` job and nothing is built, so `/api/health` never reports a version other than the image's tag. Cutting a release is therefore: move Unreleased under `## [X.Y.Z] - date` in `CHANGELOG.md`, set `springform-version`, merge, tag `vX.Y.Z`. **In a fork** (`FORK.md` present) `springform-version` is upstream's and cannot be edited, so a fork tag is `v<springform-version>-<fork>.N` (`v0.1.1-acme.3`); the job accepts any `v<version>-…` tag there, and every fork tag moves the fork image's `:latest` (`forks.md` §6).
3. **Platform: `linux/amd64` only.** An arm64 build under QEMU (buildx on a 4-vCPU VM, like a GitHub runner) spent 40 minutes compiling the SQLite amalgamation alone, and its next emulated step was still running an hour later, far past a reasonable release job. Arm servers wait for a native arm64 runner job (`ubuntu-24.04-arm`) or a SQLite stage cross-compiled on the build platform, then a manifest that joins the two.
4. **Pins.** Every action is pinned to a commit SHA. The build uses the runner's own `docker build`, no build action.
5. **Package visibility: nothing to do by hand.** The build labels the image `org.opencontainers.image.source=<repository URL>`, so GitHub links the package to the repository and gives it the repository's visibility. Upstream's package was public from its first push (checked on 2026-10-25 with an anonymous `docker pull ghcr.io/wwilson1017/springform:v0.1.1`), and a private fork's package is private. A fork's servers therefore run `docker login ghcr.io` with a token that has `read:packages` before `setup.sh` (or `deploy.sh`) pulls.

## Tests that pin this

- CI image test: `/api/health` reports `sqlite_version >= 3.51.3` and `fts5: true`.
- Restore test: snapshot + files + key → empty volume → attachment opens, credential decrypts; wrong key fails before serving.
- A fresh blob survives `sweep`; an unreferenced blob survives 6 days and goes at 8.
- Playwright: Back up now creates a file.
- Live: Multipass Ubuntu 24.04 VM dry run (`setup.sh` with `DOMAIN=localhost`, `/up`, `deploy.sh` to a second tag, restore drill into an empty volume); Railway preview with the root-owned volume.

## Source

Build plan: §13 (Dockerfile, `deploy/`, Railway), §1 (secrets, backups, restore), §2 (proxy), SQLite rules (single process, SQLite version), Decisions (Ops, Hosting), Step 5, Verification.
