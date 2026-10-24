---
title: Connecting Claude and other MCP apps
summary: Make your own MCP link so an AI app can work with your data as you, and revoke it any time.
order: 60
---
## What the link does

An MCP link lets an AI app outside this install (such as Claude) use the same tools Whisk has, **as you**. It can see what you can see and change what you can change.

Treat the link like a password. Anyone who has it can act as you until it is revoked.

## Make a link

1. Go to **Settings → MCP** and create a link. Give it a label such as "Claude on my laptop".
2. Copy it now. It is shown once and cannot be shown again.
3. Add it to your AI app:
   - **Claude (web or desktop):** add a custom connector and paste the whole link.
   - **Claude Code and similar tools:** use the server address ending in `/mcp` and send the link's token as a bearer token.

Changes made through the link happen straight away. The approval prompts in your AI app are your safeguard, so read them before you allow an action. Every action is logged.

## Revoke a link

In **Settings → MCP**, revoke any link you no longer use, or one you think someone else has seen. It stops working at once. Make a new one if you still need it.

When an admin deactivates a person, all of that person's links stop working too.
