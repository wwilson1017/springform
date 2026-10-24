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
- Admins can issue a password reset link for a member (`POST /api/auth/users/{id}/reset-link`), so
  an install without mail has a way back in for someone locked out.
- `GET /api/todos/changes?head=1` returns just the current cursor, so a client's first poll no
  longer walks the whole change journal.
- The CRM weekly touches window carries `start_day` and `end_day`, the install-local days it
  covers, which a client can send back as the `start`/`end` range.

### Changed

- A fresh install no longer runs every daily job (backup, files sweep, agent nightly) at first
  boot; a job that has never run waits for its first slot. Missed slots still catch up once.
- The outbound MCP servers migration is now `20261020000530_core_mcp_servers.sql`, so no two core
  migrations share a stamp. A development database created before this change must be recreated.

### Fixed

- Whisk names the business from the workspace name setting.
- Report CSV downloads check and default their params like the report page (bad params are 422).
- The settings API lists only keys an admin can change, so saving every listed value works.
- Example widget links open the widget page.
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
- A boot whose encryption key does not match the newest backup's logs an error with the remedy and
  records it for the Backups page, instead of serving with every stored secret silently unset.

### Schema

- Nothing deprecated.
