---
title: Requests
summary: Ask for a change or a new feature, and follow it on the Requests board.
order: 70
---
## File a request

1. Open **Requests** and choose **New request**.
2. Give it a short title that says what you need ("Show the delivery date on the order list").
3. Pick the app it is about, or the core platform.
4. Describe what you want and why. Examples help.

Your request becomes an issue in this install's GitHub project, labelled with the app, where the people who maintain the install pick it up. Your name and the app are added at the top.

## The warning on the form

The form shows a short warning chosen by your admin. It is there because requests leave this install and are read by the people who maintain it. Leave out passwords, card numbers and private customer details; describe the problem instead.

## The board

The Requests board lists requests filed from this install, newest first. Switch between open, closed and all. The board checks GitHub for updates every 15 minutes, so a request closed there shows as closed here soon after.

## For admins: connecting GitHub

Requests need two settings in the **GitHub** card of **Settings → Integrations**:

- **Repository**, as `owner/name`.
- **Token**: a GitHub fine-grained personal access token limited to that one repository, with **Issues: read and write**. It is stored encrypted and never shown again.

Until both are set, the form explains that requests are not connected yet.
