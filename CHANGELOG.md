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

### Schema

- Nothing deprecated.
