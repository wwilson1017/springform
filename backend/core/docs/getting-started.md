---
title: Getting started
summary: Set up a new install with the setup token, create the first admin, and invite your team.
order: 10
---
## The setup token

A brand-new install has no accounts. The first time it starts, it prints a one-time **setup token** in its log and saves it in the data folder as `setup-token`. If you installed with the setup script, the token is shown at the end of the script.

Nobody can become an admin without that token, so keep it private until you have used it.

## Create the first admin

1. Open the install in a browser. It sends you to the **Setup** page.
2. Paste the setup token and enter your email, your name and a password.
3. You are signed in as the first admin. The token stops working as soon as it is used.

## Invite your team

Go to **Settings → Users** and add each person with their email, name and role:

- **Member** is the everyday role for staff.
- **Admin** can also change settings, manage users, hide and order apps, run jobs and take backups.

Each invite gives you a link to send. If email is set up for the install, the link is emailed too. An invite link works for one hour; send a new one if it runs out.

The person opens the link, sets a password (or signs in with Google, if your install uses it) and lands on the launcher.

## Next steps

- Set the workspace name and timezone in **Settings → Workspace**. The timezone decides when nightly jobs run and how days are counted in reports.
- Read **Backups and restore** and store your encryption key somewhere safe today.
