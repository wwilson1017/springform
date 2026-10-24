---
title: Scores, temperature and touch counts
summary: What the lead score, the temperature and the touch-count pill on a deal mean and where they come from
order: 14
---
## The lead score

A number from 0 to 100 on every deal and every person. It is plain arithmetic, no AI, and works
with no AI keys at all. For a deal it starts from a baseline for the stage and adjusts for how much
has been logged against it, its value, whether it is linked to a person and an organization, how
long since anything happened, how old it is, and its temperature. An open deal stays between 1 and
99; a won deal scores 100 and a lost one 0. Nobody writes the score directly; it is recomputed when
a deal or its activity changes.

The score alone tells you little you can act on. Lead with the deal's health flags: stale (nothing
has happened for the staleness window, 14 days by default), stuck in its stage, missing a person or
an organization.

## Temperature is your judgement

A deal's **temperature** is set by a person: hot, warm, cold, or not set. Not set is the honest
state of a deal nobody has triaged; it is neutral, not cold. Hot deals that have gone quiet head the
dashboard's Today list.

## Top deals

The dashboard's Top deals are five open deals past the Lead stage, ranked by value with probability
tipping the order: a deal counts at 40% of its value at 0% probability, rising to its full value at
100%. A big likely deal beats a small near-certain one.

## The touch-count pill

An estimate of how many real conversations a deal has had, read from its notes, comments, activity
and notes field by the light AI model every couple of minutes. Under 5 is the dead zone, 5 to 12 is
roughly where deals close, 13 and up is a long cycle. Opening the deal shows the line-by-line
judgement behind the number, and says when the explanation no longer matches the deal.

**This one needs an AI provider.** With no key nothing is counted and the pill is simply not shown.
An admin can turn counting off in Settings → CRM.
