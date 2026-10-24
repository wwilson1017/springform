---
title: Moving deals in bulk
summary: Select several cards and move them to one stage, and what happens when some cannot move
order: 13
---
## What exists

One bulk operation: **moving deals to another stage**. There is no bulk archive, delete, reassign
or merge.

Tick the cards you want, pick a stage, apply. There is no confirmation: moving them back undoes it.

## Limits and failures

- At most **200 deals** per move. A bigger request is refused and nothing moves.
- A deal already in the target stage is skipped entirely, so its last-updated time and its
  staleness do not change.
- A deal that has gone, that you may not change, or that is archived is reported on its own line
  while the rest of the selection still moves. One bad deal does not sink a selection of fifty.
- Each moved deal gets its stage history and its timeline entry, exactly as a single move would.

## Closing in bulk

Moving deals into Won in bulk dates them today (or the one day you give for the whole batch);
moving into Lost records no reason. If the reasons or the exact days matter, close the deals one at
a time with Mark won and Mark lost.
