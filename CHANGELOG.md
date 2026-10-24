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

### Changed

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

### Fixed

- Whisk names the business from the workspace name setting.
- Report CSV downloads check and default their params like the report page (bad params are 422).
- The settings API lists only keys an admin can change, so saving every listed value works.
- Example widget links open the widget page.
- The header's app links follow the order set in Settings, like the launcher.
- Person and organization pages show the Fields and Reminders headings once, without a "Services"
  heading over them.
- The frontend lint config scopes the fast-refresh rule off for app entry, route and context modules,
  so the code carries no `eslint-disable` comments.

### Schema

- Nothing deprecated.
