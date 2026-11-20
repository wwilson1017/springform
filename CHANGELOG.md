# Changelog

Notable changes to Springform. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versions follow [Semantic Versioning](https://semver.org/). `springform-version` holds the current
version and `/api/health` reports it.

Conventions:

- A PR with a user-visible change adds a line under **Unreleased**, in `Added`, `Changed`, `Fixed`
  or `Removed`.
- A release moves Unreleased under `## [X.Y.Z] - YYYY-MM-DD`, bumps `springform-version`, and is
  tagged `vX.Y.Z`; the tag publishes the image.
- **Schema**: within a major version core never drops or renames a table or column. A core column
  or table that core stops using is listed under `Schema` as
  `Deprecated: core_<table>.<column> (since X.Y.Z)`. It stays in place, nullable and unused, until
  the next major release, which may drop it and ships a baseline migration. Apps must stop reading
  it before raising `requires_core` past that major.

## [Unreleased]

### Added

- Whisk can search the web and read a web page (`core_web_search`, `core_web_fetch`). What it reads is treated as untrusted, so every later change in that conversation asks for approval. Search is DuckDuckGo by default, or Anthropic's own web search while Whisk runs on Anthropic; admins switch both in Settings, AI, Web. Page reads never reach private or local addresses, including through redirects.

### Changed

- Outbound MCP also refuses NAT64, 6to4 and IPv4-compatible IPv6 addresses.

- CI also checks formatting (`ruff format`, Prettier) and types (pyright), and installs from `uv.lock` with `--locked`. `scripts/check.sh` runs the same checks locally, and `scripts/new-app.sh` formats the app it writes so a new app passes them. A fork whose app tests trip pyright's Optional-access rules adds its tests folder to `executionEnvironments` in `pyproject.toml` (`docs/agents/forks.md`).

### Removed

- `railway.json`. Railway stops reading it on 2026-12-01, and `.railway/railway.ts` now holds the build, health check and restart settings. Railway has no place to store the required `/data` mount, so nothing refuses a deploy without the volume any more: attach it when you create the service.

## [0.1.3] - 2026-11-16

Two fixes: the phone menu on installs with many apps, and a random crash in the backend test run.

### Fixed

- The phone menu now scrolls, so Settings and Sign out stay reachable when an install has more apps than fit on the screen.
- The backend test run no longer dies at random with a segmentation fault (CI exit 139). MCP discovery at boot is now the `core.mcp_discover` job (new `Job(on_boot=True)`), which shutdown cancels and waits for (up to 10 s), instead of an unmanaged thread that could still be reading the database as it closed; when a job outlives that wait, shutdown now leaves the database open for the process exit to close. Core and apps start no threads of their own (a test scans for them), and a test that leaves a thread running stops the run by name.

## [0.1.2] - 2026-11-15

Fixes from building the first apps in a fork, a hardened public demo, and the brand.

### Added

- `requires_apps` in `app.json`: an app lists the apps its sample data builds on, and their samples run first (on boot and in the nightly preview reset). Apps that list none keep folder-name order; an unknown app or a cycle stops startup.
- `notifications.deliver_in(..., role="admin")` notifies every active admin (or every user with another role) in one call, so an app no longer queries `core_users` itself.
- `.railway/railway.ts` (Railway Infrastructure as Code): applied once per service, it stores the Dockerfile build, `/up` health check, restart policy and required `/data` mount before Railway stops reading `railway.json` on 2026-12-01, and leaves the service's source, variables and volume as they are.
- Security headers on every response, including errors: nosniff, same-origin frame protection, referrer policy and HTTPS-only HSTS.
- Brand mark (`brand/springform-mark.svg`: a foundation of app tiles with one lifting off on a spring) with a short brand note, a README header, the app favicon, and the myspringform.com site in `site/`, published by a GitHub Pages workflow that runs only in the upstream repository.
- myspringform.com: a link-preview card (`og:image`, `twitter:card`), a canonical URL and fuller title, a styled 404 page, `robots.txt` and `sitemap.xml`; the header stays on one row on phones with 44 px tap targets.
- `SECURITY.md`: supported versions, how to report a vulnerability privately, what to expect, and scope; linked from the README.
- Preview installs restore sample data and remove uploaded files nightly at 09:00 install-local (UTC by default), with reset history on the Jobs page.
- myspringform.com and the README link the live demo at demo.myspringform.com: a Try the demo button with a one-line note in the hero, and a Demo link in the header (on phones it takes Example's place).

### Changed

- `backend/tests/conftest.py` is now the pytest plugin `backend/testing/fixtures.py`, loaded by a root `conftest.py`. A fork deletes any app-level conftest that re-imported core's fixtures (it would fail to import), and imports `PASSWORD` and `make_client` from `backend.testing.fixtures`.
- The app wears the brand: the accent is copper instead of red (status reds stay), and the mark sits beside the name in the header and on the sign-in page. A fork replaces the mark through `frontend/public/branding/`.

### Fixed

- New apps scaffold typed routes, app-prefixed models, an internal service and the supported `grid` icon, without unused API or settings modules; CI checks the generated scaffold.
- `docs/agents/agent.md` (registry rule 5) says a write tool that only creates a record returns an empty `targets` list, and when an existing record it touches still belongs in `targets`.
- Report tables show `*_cents` columns as money (171720 reads 1,717.20, under a "revenue" header), the way the Timeline does. The CSV download keeps the cents.
- The Timeline custom-field label test no longer fails at random in CI: it now waits for the field's real label instead of matching the humanized key it falls back to.
- Whisk approval cards show a plain summary of the action, or only its name and arguments, instead of model-facing tool instructions.
- Fork apps can declare settings and report parameters without changing core's response-shape fixture.
- The app contract test fails when two apps define Pydantic models with the same class name, naming the model and both apps, instead of letting a new app silently rename another app's generated API types; the CRM and Todos share `Badge` and `Deleted` from `backend/core/responses.py` (#10).
- The Browser smoke's Settings test checks that core's and the upstream apps' sections are present instead of the exact list, so a fork app's settings card no longer fails it.
- App tests in `backend/apps/<slug>/tests/` now run under `uv run pytest` and in CI, with the shared fixtures and the skip/xfail ban and no conftest of their own; `scripts/new-app.sh` scaffolds the folder (#8).
- `/docs`, `/redoc` and `/openapi.json` need a signed-in user; signed out they return 401, so an install no longer publishes its API schema.
- Railway builds: the Dockerfile no longer declares `VOLUME /data`, which Railway refuses ("docker VOLUME is not supported, use Railway Volumes"). Every supported run mounts `/data` itself.
- deploy.md no longer asks the owner to make the ghcr package public by hand: the image's source
  label links it to the repository, which sets its visibility.
- `update-from-upstream.sh` labels its PR `no-auto-merge` and the PR body asks for a merge commit:
  a squash drops upstream's history and makes the next update conflict. The body mentions the
  regenerated types file only when it changed.
- Preview mode no longer accepts a secret setting (Google sign-in client, Sheets service-account key):
  the save is refused with "Preview mode does not store secrets.", so a visitor can no longer stop the next boot.
- The app contract accepts both cross-app `api` import forms, allows app tests to import another app's `seed`, and recognizes relative imports that stay within the app.

## [0.1.1] - 2026-10-25

Fixes from the first run of the fork tooling against a throwaway fork.

### Changed

- Fork releases: a fork tags `v<springform-version>-<fork>.N` (core is pinned, so the version file
  cannot move), the release workflow accepts those tags in a fork and every one of them moves the
  fork image's `:latest`. Upstream tags still have to equal `v` + `springform-version`.
- Agent docs state the app icon vocabulary, the two search endpoints, the CRM jobs' keyless
  behaviour and where connected Google Sheets are managed, in place of four open questions.

### Fixed

- `new-fork.sh` no longer exits while waiting for the fork's first CI run (the workflow registers a
  few seconds after the push), and sets `gh`'s default repo to the fork in the clone so `gh` never
  resolves to the public upstream there. `seed-labels.sh` without `--repo` and
  `update-from-upstream.sh` take the repo from `origin` for the same reason.
- `update-from-upstream.sh` installs frontend dependencies before regenerating types, so it works
  in a fresh clone, and fetches the upstream tag from the URL in `FORK.md`, so it does not need an
  `upstream` remote.
- `new-app.sh` scaffolds a model name prefixed with the app (`NotesItemIn`), so generated types do
  not collide with Todos', and a `docs/index.md` with the front matter the Guide requires; it ends by
  naming the type generation and label steps.
- Browser smoke: the launcher and hidden-app specs check that the built-in apps are present or
  absent instead of matching the whole list, so a fork's own apps do not turn the job red.

## [0.1.0] - 2026-10-25

The first release: the platform core, the built-in CRM and Todos apps, Whisk, MCP in and out, the
deploy kit and the fork tooling.

### Added

- Backups page: a warning when the server's encryption key does not match the newest backup, naming
  the manifest and linking the Guide's backups topic.
- Settings, Users: admins make a one-time password reset link for another account, to copy, and see
  when it was emailed too.
- Record services UI: custom fields on records with an admin field editor, saved views, a Reports
  page with CSV download, the notification bell and Notifications page, browser push, Reminders
  (page and record panel), @-mentions in notes, and file thumbnails.
- Repository tooling: CI for upstream and forks, Docker image with SQLite 3.51.3, one-script VPS
  deploy, fork scripts and release workflow.
- Outbound MCP: admins connect Whisk to other MCP servers (Settings, MCP servers); every remote
  tool call asks for approval, results are treated as untrusted, and private addresses are refused.
- Setting `agent.context_budget_chars`: how much business memory Whisk reads per turn.
- The workspace API returns the install's public URL (`PUBLIC_URL`) for Settings to show read-only.
- Todos screens: Today, Inbox triage, To Do, Waiting, Someday, Done, Projects, Areas, Review, search
  and a page per todo, with a private/team switch and an assignee on todos, projects and areas, a
  Mine / Everyone switch, changes from others every 30 seconds, a To-dos panel on people and
  organizations, and a Settings card for the default visibility.
- The Todos filters answer carries `default_visibility`, so members see the default too.
- Settings: editable workspace name and timezone, app hide/show and reorder, GitHub and Google Sheets
  integrations, export download and upload limit; a Backups page with "Back up now", downloads and the
  one-time encryption-key reveal.
- MCP connector: each person can make a link in Settings that lets claude.ai, Claude Desktop or
  Claude Code use Whisk's tools as them. Links can be revoked, and stop working when the person is
  deactivated.
- People and Organizations pages: search, tag, organization and archived filters, duplicates and
  merge, contact details and addresses with a primary, roles between people and organizations,
  and a contact picker other screens can reuse.
- Whisk chat at `/whisk`: streamed answers, an approval card before any write, and a conversation
  list with search, rename, private and delete. Settings, AI holds the provider keys, the agent,
  memory (context files and facts) and the nightly run.
- Admins can issue a password reset link for a member (`POST /api/auth/users/{id}/reset-link`), so
  an install without mail has a way back in for someone locked out.
- `GET /api/todos/changes?head=1` returns just the current cursor, so a client's first poll no
  longer walks the whole change journal.
- The CRM weekly touches window carries `start_day` and `end_day`, the install-local days it
  covers, which a client can send back as the `start`/`end` range.
- App manifest field `hidden_by_default`: the app starts hidden from members on an install that has
  not seen it before; an admin's later show or hide always wins.
- The Backups overview carries `key_mismatch`, the newest backup manifest taken under another
  encryption key (null when they match), and `/api/health` carries `key_mismatch` as true or false.
- People and organization rows and details carry `owner_name`, so an owner shows by name instead of
  "User #n".
- Whisk can find, read, create and link people and organizations, add a note to any record and set
  or list the user's reminders. Creating or linking contacts waits for the user's approval; notes
  and reminders happen at once. MCP links get the same tools.

### Changed

- One type-to-search user picker for record owners (people, organizations, deals), the CRM owner
  filter and user custom fields. Members can pick any active user, and an owner reads by name.
- CRM Weekly touches shows its window by the install-local days the server applied
  (`start_day`, `end_day`) and carries those days to a rep's page.
- Todos pages start their change feed from the current rev (`GET /api/todos/changes?head=1`)
  instead of walking the whole journal on every page load.
- A member who opens an admin-only page sees "Not allowed" with a link home, instead of being sent
  somewhere else.
- The example app serves a widget at one URL, `/example/<id>`, the one the backend links to; the
  `/example/widgets/<id>` alias is gone.
- A fresh install no longer runs every daily job (backup, files sweep, agent nightly) at first
  boot; a job that has never run waits for its first slot. Missed slots still catch up once.
- The outbound MCP servers migration is now `20261020000530_core_mcp_servers.sql`, so no two core
  migrations share a stamp. A development database created before this change must be recreated.

### Fixed

- CRM deal page: shows the deal's custom fields and reminders beside its files, as the CRM Guide says.
- Whisk names the business from the workspace name setting.
- Report CSV downloads check and default their params like the report page (bad params are 422).
- The settings API lists only keys an admin can change, so saving every listed value works.
- Example widget links open the widget page.
- Timeline field changes name custom fields by their label, show amounts as money, users by name
  and columns in words ("Value", not "value_cents"), and a custom field save shows up in the
  timeline at once.
- The header's app links follow the order set in Settings, like the launcher.
- On a phone the Settings section links wrap instead of scrolling sideways, so every section and
  the one you are on stay in view.
- Person and organization pages show the Fields and Reminders headings once, without a "Services"
  heading over them.
- The frontend lint config scopes the fast-refresh rule off for app entry, route and context modules,
  so the code carries no `eslint-disable` comments.
- Preview accounts no longer show as pending invites, and the last-admin guard counts them.
- Organization names and duplicate checks fold case beyond ASCII: "café ñandú" now collides with
  "Café Ñandú", and "ZOË DÉMO" is found as a duplicate of "Zoë Démo".
- The app contract test accepts a `UNIQUE` constraint on an app's own table (SQLite's
  `sqlite_autoindex_*`), as the apps contract doc already allowed.
- A CRM deal merge leaves a system row on the surviving deal's timeline instead of a note in the
  merging user's name, so it no longer counts as a touch. Apps can write system rows through
  `timeline.api.add_system_in`.
- Preview seeds core's sample people and organizations before any app's sample data, so an app's
  sample (the CRM's deals) no longer has to seed them itself.
- A `springform-version` that is not a PEP 440 version (such as `0.1.0-dryrun-b`) stops the boot
  with a message naming the file and the value, instead of an uncaught `InvalidVersion`.
- A second backup in the same second (a frozen clock, a double click on "Back up now") is saved as
  `<stamp>-2`, `-3`, … instead of failing with "already exists".
- The Example app is hidden from members on a fresh install, as its tile and the docs say.
- A boot whose encryption key does not match the newest backup's logs an error with the remedy and
  records it for the Backups page, instead of serving with every stored secret silently unset.

### Schema

- Nothing deprecated.
