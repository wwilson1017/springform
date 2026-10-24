---
title: Whisk, the assistant
summary: What Whisk does, adding an AI key, and why it asks before changing anything.
order: 50
---
## What Whisk is

Whisk is the built-in assistant. It can look things up across your apps and the people directory, answer questions about your records, and make changes when you ask, such as adding a note or creating a record. Whisk sees only what you are allowed to see.

## AI keys

Whisk needs an AI provider key, which an admin adds in **Settings → AI**. Keys are stored encrypted.

With no key, everything else works normally. The Whisk page shows a card saying a key is needed, with a link to Settings for admins. Nightly AI work is skipped too.

## Confirmations

Before Whisk changes anything, it shows you what it wants to do with an **Approve** button. Nothing is written until you approve. A few routine changes may skip the button; anything bigger always asks.

If the change is no longer valid by the time you approve (for example the app was updated in between), Whisk tells you and does not run it.

Whisk says what it changed after each action, and the record's timeline shows the change.

## Nightly work

When an admin turns it on, Whisk reviews the day's conversations overnight to keep its notes up to date. This uses your AI key, so it is off until switched on in Settings. Unattended work can only read, never change records.
