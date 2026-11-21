---
title: {agent_name}, the assistant
summary: What {agent_name} does, adding an AI key, and why it asks before changing anything.
order: 50
---
## What {agent_name} is

{agent_name} is the built-in assistant. It can look things up across your apps and the people directory, answer questions about your records, and make changes when you ask, such as adding a note or creating a record. {agent_name} sees only what you are allowed to see.

## AI keys

{agent_name} needs an AI provider key, which an admin adds in **Settings → AI**. Keys are stored encrypted.

With no key, everything else works normally. The {agent_name} page shows a card saying a key is needed, with a link to Settings for admins. Nightly AI work is skipped too.

## Confirmations

Before {agent_name} changes anything, it shows you what it wants to do with an **Approve** button. Nothing is written until you approve. A few routine changes may skip the button; anything bigger always asks.

If the change is no longer valid by the time you approve (for example the app was updated in between), {agent_name} tells you and does not run it.

{agent_name} says what it changed after each action, and the record's timeline shows the change.

## Skills

A skill is a short, named method, such as how your business does its weekly stock count. {agent_name} sees the name and a one-line description of every active skill, and reads its steps when a task calls for one. Admins manage them in Settings, AI, Skills: write one by hand, or turn on the skills review, and {agent_name} proposes skills from conversations that are not private. A proposal is never used until an admin approves it. Skills nobody has used for 60 days are archived (never deleted) unless pinned.

## Nightly work

When an admin turns it on, {agent_name} reviews the day's conversations overnight to keep its notes up to date. This uses your AI key, so it is off until switched on in Settings. Unattended work can only read, never change records.
