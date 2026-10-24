---
title: Pipeline stages
summary: The six deal stages, closing a deal as won or lost, the Closed on date and stage checklists
order: 11
---
## The six stages

In order: **Lead, Qualified, Proposal, Negotiation, Won, Lost**. Lead through Negotiation are the
open stages; Won and Lost are closed. A deal's **status** reads `open`, `won` or `lost` and always
follows its stage.

There is no preset probability per stage. A new deal starts at 0% unless you set one. Closing is
the exception: moving a deal into Won sets its probability to 100%, into Lost to 0%, whatever the
form said. After the close, editing the probability is up to you.

## Moving a deal

Drag a card between columns, change the stage on the deal, or select several cards and move them
together (see the bulk moves topic). Every move is recorded with who made it and when, so the
deal's history and the pipeline analytics can show how long it sat in each stage. A move to the
stage a deal is already in changes nothing, not even its last-updated time.

## Closing a deal properly

Use **Mark won** and **Mark lost** rather than dragging into those columns:

- **Mark won** asks for the day it closed. The default is today; an earlier day is fine; a future
  day is refused.
- **Mark lost** asks for the reason. The reason is stored on the deal and shows in its history.
  Dragging into Lost or a bulk move closes the deal with no reason, and the lost reason is the most
  useful field when you review a quarter.

Reopening a lost deal clears its reason, so it never carries a stale one.

## The Closed on date

The expected close date is a forecast; **Closed on** is the fact. It is set when a deal enters Won
(today, or the day you give), kept if the deal is marked won again, and cleared if the deal leaves
Won. While a deal is won you can correct the day, but not blank it. Days follow the business's time
zone (Settings → General), so a deal won late in the evening is dated that evening, not tomorrow.

## Stage checklists

Every stage has a short summary and a checklist of what it takes for a deal to belong there. The
CRM ships a standard set; an admin can rewrite any stage's summary and checklist, and **Reset to
standard** puts it back. Everyone sees the criteria; only admins edit them.

## Deal fields

Title, value and currency, a probability, an expected close date, Closed on once won, a
temperature (hot, warm, cold or not set), notes, an owner, and links to a person and an
organization from the shared directory. Values are stored in cents, so totals never drift by a
fraction of a cent. Notes, attachments, custom fields and reminders work on a deal as on any other
record.
