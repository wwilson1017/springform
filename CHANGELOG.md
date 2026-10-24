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
- Setting `agent.context_budget_chars`: how much business memory Whisk reads per turn.
- The workspace API returns the install's public URL (`PUBLIC_URL`) for Settings to show read-only.
- Settings: editable workspace name and timezone, app hide/show and reorder, GitHub and Google Sheets
  integrations, export download and upload limit; a Backups page with "Back up now", downloads and the
  one-time encryption-key reveal.

### Changed

- A fresh install no longer runs every daily job (backup, files sweep, agent nightly) at first
  boot; a job that has never run waits for its first slot. Missed slots still catch up once.

### Fixed

- Whisk names the business from the workspace name setting.
- Report CSV downloads check and default their params like the report page (bad params are 422).
- The settings API lists only keys an admin can change, so saving every listed value works.
- Example widget links open the widget page.

### Schema

- Nothing deprecated.
