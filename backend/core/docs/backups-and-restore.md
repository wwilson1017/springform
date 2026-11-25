---
title: Backups and restore
summary: Nightly backups, the encryption key you must keep, off-site copies and restoring.
order: 80
---
## What is backed up

Every night at 03:00 (in the install's timezone) the install saves a **recovery set**: a copy of the database, a list of the attached files it needs, and a check that it was written completely. The newest 7 sets are kept, and the files they need are never deleted while a set lists them.

Admins can take one now with **Back up now** on the **Backups** page, and download a set from there.

## The encryption key: keep it safe

Passwords and keys stored in the install (AI keys, the GitHub token, Google sign-in secrets) are encrypted with the install's **encryption key**. A backup without that key restores your records but not those stored secrets. **The key is not in any backup**, on the server or off-site.

- The Backups page shows the key **once**. Copy it into your password manager or another safe place that is not this server and not your backup bucket.
- If your install sets the key in its environment file instead, the page says so; keep that file safe.

## Off-site copies

A backup on the same server does not survive the server. Under **Off-site copy** on the Backups page, an admin can set a storage bucket of your own on any S3-compatible service (AWS S3, Cloudflare R2, Backblaze B2, MinIO).

**We recommend Cloudflare R2**, free for small installs: [Set up Cloudflare R2](/guide/backups-cloudflare-r2) walks through it click by click, and [Set up backups with an AI agent](/guide/backups-agent-setup) lets an agent such as Claude Code do it for you. How the copy works, with any provider:


- Enter the endpoint, bucket, region (`auto` for R2), an optional folder (prefix) and an access key. **Test connection** writes a small file, reads it back and removes it; save your changes before testing. Settings cannot change while a backup is running.
- After each backup, nightly and on **Back up now**, the set goes up: the attached files first (each only once), then the database, then the list, so a copy is only complete once its list has arrived. Sets past the number you keep (30 by default) are removed from the bucket. On a bucket that keeps old versions (Backblaze B2 does by default), removed files are only hidden and still billed: add a lifecycle rule that deletes hidden versions. B2's "Keep only the last version of the file" preset covers the whole bucket, so use it only on a bucket that holds nothing but these backups; otherwise make a rule for your folder (prefix) that deletes hidden files after 1 day.
- The page shows the last good upload and the last error. If no good upload has happened in about two days, or the last one failed, admins see a warning bar on every page.

**Backup passphrase (optional).** With a passphrase, everything uploaded and every download is encrypted with [age](https://age-encryption.org) and ends in `.age`. Anyone with the passphrase can open it with the free `age` tool, no Springform needed. **If you lose the passphrase, those backups cannot be opened; nobody can recover it.** Each new passphrase starts a new `age-…` folder in the bucket, so older sets keep working with the passphrase they were made with.

## Restoring

Restoring is done on the server with the restore script and the recovery set's list. It checks that the set is complete, copies it into an empty data folder and checks the encryption key. With the wrong key it stops with a clear "wrong key" error rather than starting with unreadable secrets.

From the bucket:

1. Download the set's folder (the prefix, or its `age-…` folder) with any S3 tool, so you have its `backups/` and `files/` folders.
2. If it is encrypted, decrypt each `.age` file: `age -d -o <name> <name>.age`, entering the passphrase.
3. Run the restore on that folder, with the encryption key you kept.

A test restore's copy still holds the bucket settings: remove them before it first starts, or it would upload into, and prune, your real backups. The server guide (`docs/agents/deploy.md`) has the exact commands.

Practise a restore once, before you need it.
