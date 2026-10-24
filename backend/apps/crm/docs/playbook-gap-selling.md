---
title: Gap Selling
summary: Keenan's problem-centric discovery — map the buyer's current state against the future state they want, because the gap between them is the value of the deal.
order: 32
---
## Core ideas

- **The gap is the deal.** The distance between where the buyer is now and where they want
  to be is the entire value of what you sell. A small gap is a small deal no matter how
  much the buyer likes you, and a buyer with no gap is not a buyer.
- **Nobody buys a product; they buy a changed situation.** Keenan's framing is that every
  purchase is a move from a present state the buyer dislikes to a future state they prefer.
  Your job is to understand both ends precisely enough to measure the distance.
- **Map the current state in detail.** Not just the problem — the process, the numbers, the
  people affected, what has already been tried. A current state described in one sentence
  is a discovery that has not happened.
- **Find the root cause, not the symptom.** The buyer names a symptom ("reporting takes too
  long"). The cause is usually upstream ("three systems disagree, so everything is
  reconciled by hand"). Selling against the symptom produces a solution the buyer does not
  need and a deal that unravels later.
- **Problems have physical, technical and personal impact.** The hard costs are the easy
  part. The impact on the person you are talking to — their credibility, their weekend,
  their promotion — is what actually creates urgency, and it never appears on a cost
  sheet.
- **Quantify, then let the buyer confirm the number.** Value you assert is marketing; value
  the buyer states is a business case. Get them to say what the gap costs.
- **Discovery is the sale.** Keenan is blunt that the demonstration, the proposal and the
  close are downstream consequences of discovery. A great proposal cannot rescue a deal
  where nobody established what was broken.
- **Qualify out loudly and early.** A buyer with no gap, no urgency or no ability to change
  is a deal you should lose in week one rather than week twenty. Keeping it alive to keep
  the pipeline looking healthy is the expensive mistake.
- **You must know the buyer's business.** Being useful requires enough domain knowledge to
  recognize when an answer is unusual. A seller who cannot tell a normal number from an
  alarming one cannot find a gap.
- **"Why change?" outranks "why us?"** Most lost deals never needed a competitor. They
  needed a reason to do anything at all this quarter.

## When Whisk reaches for it

- **The value narrative is weak** — the user cannot say in one sentence what the buyer
  gets, or the deal value looks arbitrary.
- **Qualification is the question** — a new deal in *lead* and the user is deciding whether
  it deserves real effort.
- **The record has a solution but no problem** — notes describe what was demonstrated,
  never what was broken.
- **A deal has been re-scoped downward repeatedly** — usually a sign the original gap was
  never real.
- **The buyer says they are fine as they are** — the honest answer may be that there is no
  gap, and finding that out in week one is a win.
- **A lost deal needs a reason** — reconstructing the gap you never established is the
  cheapest post-mortem there is.

## Applied to the CRM

- **Current state and future state belong in writing on the deal** — two short paragraphs in a
  note, so anybody reading the record later can see the gap rather than infer it.
- **Check what this install records before inventing a field** — the deal's custom fields are
  set up in Settings. If one fits, use it; if none does, the note is the right home.
- **Let the record start qualification, then read the rest** — a deal with no value, no
  expected close date and no linked person (`crm_get_deal`, `crm_get_deal_health`) is a deal
  nobody has worked, and it is where Keenan's qualifying-out conversation begins. Whether a
  real problem was ever established is in the deal's notes and activity
  (`crm_get_activity_log`): read them before concluding there is no gap.
- **Size the deal from the gap, not from hope** — when the buyer states what the problem
  costs, update the value with `crm_update_deal` (in cents), and say in a note where the number
  came from.
- **A qualified-out deal gets closed, not left to rot** — `crm_mark_deal_lost` with "no
  compelling reason to change" as the reason keeps the pipeline honest. Losses are not grouped
  by reason anywhere, so the reasons are read on the deals themselves (`crm_search_deals` with
  the stage set to lost); `crm_analytics` gives the win and loss counts behind them.

## Go read it

Keenan, *Gap Selling* (Sales Guy Publishing, 2018). The discovery chapters are worth the
book on their own, and the tone is a deliberate provocation — it is written to make a
comfortable seller uncomfortable about how little their notes actually say.
