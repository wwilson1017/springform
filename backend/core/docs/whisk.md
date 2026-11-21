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

When you deny a change you can say why in the box under the buttons. {agent_name} is told your reason and not to retry it or find a way around it; after three denied steps in a row it is told to stop and report back to you.

Tick **Always allow** on an Approve card and that tool stops asking in your chats with {agent_name}. See and remove these under **Settings → Account → Saved approvals**. {agent_name} still asks for tools that always ask, for anything that reaches outside the workspace or deletes data for good, for a change that would hide a record from others, and in any conversation where it has read outside content, such as a web page.

If the change is no longer valid by the time you approve (for example the app was updated in between), {agent_name} tells you and does not run it.

{agent_name} says what it changed after each action, and the record's timeline shows the change.

## Check-ins

A check-in is a question {agent_name} asks for you on a schedule: every so many minutes, every day at a time, or one day a week. Set them up with **Check-ins** under the conversation list on the {agent_name} page. {agent_name} runs each one as you, with look-up tools only, so a check-in can read but never change anything. Its answer arrives as a notification that opens the conversation; when there is nothing worth telling you, it sends nothing. Pause, resume, run now or delete one from the same list. If one fails three times in a row you get a notification, and after ten it is paused until you resume it. Check-ins use your AI key.

## Nightly work

When an admin turns it on, {agent_name} reviews the day's conversations overnight to keep its notes up to date. This uses your AI key, so it is off until switched on in Settings. Unattended work can only read, never change records.
