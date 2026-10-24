---
title: Backups and restore
summary: Nightly backups, the encryption key you must keep, off-site copies and restoring.
order: 80
---
## What is backed up

Every night at 03:00 (in the install's timezone) the install saves a **recovery set**: a copy of the database, a list of the attached files it needs, and a check that it was written completely. The newest 7 sets are kept, and the files they need are never deleted while a set lists them.

Admins can take one now with **Back up now** on the **Backups** page, and download a set from there.

## The encryption key: keep it safe

Passwords and keys stored in the install (AI keys, the GitHub token, Google sign-in secrets) are encrypted with the install's **encryption key**. A backup without that key restores your records but not those stored secrets.

- The Backups page shows the key **once**. Copy it into your password manager or another safe place that is not this server.
- If your install sets the key in its environment file instead, the page says so; keep that file safe.

## Off-site copies

A backup on the same server does not survive the server. The setup script offers a nightly copy to cloud storage. It copies the attached files first, then the database, then the list, so a copy is only complete once its list has arrived.

## Restoring

Restoring is done on the server with the restore script and the recovery set's list. It checks that the set is complete, copies it into an empty data folder and checks the encryption key. With the wrong key it stops with a clear "wrong key" error rather than starting with unreadable secrets.

Practise a restore once, before you need it.
