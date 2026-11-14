<p align="center">
  <a href="https://myspringform.com">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="brand/springform-mark-dark.svg">
      <img src="brand/springform-mark-light.svg" width="112" height="112" alt="Springform">
    </picture>
  </a>
</p>

<h1 align="center">springform</h1>

<p align="center"><b>Small-business software, minus the plumbing.</b></p>

<p align="center">
  <a href="https://myspringform.com">myspringform.com</a> ·
  <a href="https://github.com/wwilson1017/springform/releases">Releases</a> ·
  <a href="CHANGELOG.md">Changelog</a> ·
  <a href="docs/agents">Contract docs</a> ·
  <a href="SECURITY.md">Security</a> ·
  MIT
</p>

An open-source foundation for small-business software. One SQLite file, one process, one container.
FastAPI + React. Apps live in their own folders and are discovered on a launcher; a client gets a
private fork that pulls platform updates and never edits core.

**Status: early.** v0.1 is released and runs; expect the contracts to keep moving until 1.0.

- Core: login (password + authenticator app, Google sign-in), people and organizations, timelines,
  attachments, custom fields, saved views, reminders, notifications, a scheduler, nightly backups,
  connected Google Sheets, and an assistant named Whisk with an MCP connector.
- Built-in apps: CRM, Todos.
- Forks: `scripts/new-fork.sh` makes a private client repo with a fetch-only `upstream`; CI fails any
  change outside the app folders.

License: MIT.

## Run it

Development, with Python 3.12, [uv](https://docs.astral.sh/uv/) and Node 22:

```bash
uv sync && (cd frontend && npm ci && npm run build)
uv run uvicorn backend.main:app --reload      # http://localhost:8000, data in ./data
```

Or the image: `docker build -t springform . && docker run -p 8000:8000 -v springform-data:/data springform`.
On first boot the log prints a one-time setup token (also in `/data/setup-token`) for creating the
first admin.

## Deploy

**A server.** On a fresh Ubuntu 24.04 machine whose DNS name already points at it:

```bash
git clone https://github.com/wwilson1017/springform.git
sudo DOMAIN=crm.example.com springform/deploy/setup.sh
```

It installs Docker, opens only ports 22/80/443, turns on automatic security updates, writes
`/srv/springform/.env` with fresh secrets, starts the app behind Caddy (automatic HTTPS), prints the
setup token, and offers a nightly off-site copy of the backups with rclone. Update later with
`sudo /srv/springform/deploy.sh`. A fork runs its own image: set `IMAGE=` in `.env` (and run
`docker login ghcr.io` first if the image is private). A fork may edit anything under
`backend/apps/` and `frontend/src/apps/`, built-in apps included, by design; CI's Fork scope job
fails any other change that departs from the pinned upstream release.

**Deploys are stop-before-start.** SQLite has one writer, and the app holds a lock on
`/data/.springform.lock` so a second copy refuses to start. `docker compose up` stops the old
container before starting the new one, so expect a few seconds of downtime per deploy. Never run
two copies against one `/data`, and never raise `--workers` above 1.

**Railway.** `railway.json` builds the Dockerfile, health-checks `/up` and requires a volume at
`/data`. Set `SECRET_KEY`, `PUBLIC_URL`, `TRUST_PROXY=1` and `RAILWAY_DEPLOYMENT_DRAINING_SECONDS=15`
(time for a graceful shutdown). With a volume attached, Railway stops the old deployment before
starting the new one, which the lock relies on.
