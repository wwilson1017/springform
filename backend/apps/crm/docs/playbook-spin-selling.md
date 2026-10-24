---
title: SPIN Selling
summary: Rackham's research-backed questioning sequence — situation, problem, implication, need-payoff — for discovery calls and early deals with no stated problem.
order: 30
---
## Core ideas

- **The findings came from watching real calls, not from theory.** Rackham's team observed
  thousands of sales conversations and sorted them by outcome. What separated the
  successful ones was not charisma or closing technique — it was the questions asked, and
  in what order.
- **What works on a small sale fails on a large one.** Pressure closes and urgency tricks
  can carry a cheap, one-call decision. On a large, considered purchase they raise
  resistance, because the buyer has to defend the decision to other people after you leave.
- **Situation questions gather facts, and you should ask as few as possible.** How many
  people, what system today, what the process looks like. Buyers find them tedious, and
  most of the answers can be researched before the call rather than extracted during it.
- **Problem questions surface difficulties.** What is hard about the current approach,
  where it breaks, what it costs them in effort. This is where a real conversation starts,
  and inexperienced sellers skip it to get to the demonstration.
- **Implication questions are the ones that move a large deal.** Take the problem the buyer
  just admitted and ask what it leads to: if the handoff fails twice a week, what does that
  do to the delivery date, and what does a missed delivery date do to the renewal? The
  buyer, not you, assembles the case for change — which is why it survives you leaving the
  room.
- **Need-payoff questions let the buyer argue your side.** "If we could close that gap,
  what would that be worth to you?" The answer is the buyer describing the benefit in their
  own words, and that is the sentence they will repeat to their colleagues.
- **Sell the payoff, not the feature.** Rackham separates a feature from an advantage from
  a benefit that answers a need the buyer has actually stated. Features offered before a
  need is stated generate objections; benefits offered after it generate agreement.
- **Most objections are manufactured by the seller.** They arrive when value is presented
  too early, against a problem the buyer never agreed they had. Good questioning prevents
  objections far more effectively than any technique for handling them.
- **A large sale's success is often an advance, not an order.** A call that ends with a
  specific action the buyer commits to — an introduction to the technical lead, a pilot on
  one team — is progress. A call that ends in a friendly "keep in touch" is a continuation
  that feels fine and goes nowhere.
- **Planning is where the sequence gets built.** Before the call, write down the problems
  you believe exist and the implications you would ask about. Improvised implication
  questions rarely land.

## When Whisk reaches for it

- **A deal has no stated problem** — it sits in *lead* or *qualified*, the notes describe
  the buyer's company but never what is broken.
- **A discovery call is being planned** — the user is about to meet someone new and wants
  to know what to ask.
- **A deal is moving on interest rather than need** — the buyer likes the product, and
  nobody can say what happens if they do nothing.
- **The record is thin** — the deal has a person and a value but nothing
  about the problem, the timeline or who decides.
- **Objections keep arriving early** — price and timing come up before the buyer has
  agreed anything is wrong, which is the signature of a pitch running ahead of discovery.
- **The deal is large and the user is being urged to close it** — the closing pressure
  that works on a small deal is actively harmful here.

## Applied to the CRM

- **Write the problem down, in the buyer's words** — after a discovery call the most valuable
  line on the record is the problem the buyer admitted. Put it in a note on the deal and log
  the call with `crm_log_activity`.
- **Let the record build part of the question list** — `crm_get_deal_health` flags a deal
  with no person or organization linked, and a deal with no value or close date is plain on
  `crm_get_deal`. Each blank is a situation question you have not asked. Whether a problem was
  ever written down is the question that matters: read the deal's notes and activity first.
- **An advance is a to-do with a date** — end the call with a specific commitment and create it
  with `todos_create`, linked to the deal. A deal whose only next step is "follow up" has not
  advanced, and the *no next step* health flag will say so.
- **Stage movement follows an agreed need, not a good meeting** — move *lead* to *qualified*
  with `crm_update_deal_stage` once the buyer has stated a problem and the implications of
  leaving it alone, not when they seemed enthusiastic.
- **Read what is already recorded before you ask** — `crm_get_deal` and the deal's custom
  fields often hold half the situation questions' answers. Asking a buyer to repeat something
  they already told you spends the goodwill the questions need.

## Go read it

Neil Rackham, *SPIN Selling* (McGraw-Hill, 1988). Nearly forty years on it is still the
most rigorously evidenced book on the list, and the transcripts showing an implication
question landing badly are worth more than the model itself.
