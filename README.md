# Springform

An open-source foundation for small-business software. One SQLite file, one process, one container.
FastAPI + React. Apps live in their own folders and are discovered on a launcher; a client gets a
private fork that pulls platform updates and never edits core.

**Status: under construction.** The first release (v0.1.0) is being built in the open. Nothing here is
ready to run yet.

- Core: login (password + authenticator app, Google sign-in), people and organizations, timelines,
  attachments, custom fields, saved views, reminders, notifications, a scheduler, nightly backups,
  connected Google Sheets, and an assistant named Whisk with an MCP connector.
- Built-in apps: CRM, Todos.
- Forks: `scripts/new-fork.sh` makes a private client repo with a fetch-only `upstream`; CI fails any
  change outside the app folders.

License: MIT.
