---
title: Organization report and dashboard
summary: Organization totals, the CRM dashboard, Today, weekly touches and analytics
order: 16
---
## The organization report

The CRM can total up one organization: its people, its deals, its open deal count and value, its
won value, the last time anything happened on any of its deals, and its recent activity. It is
read-only and leaves archived deals out. There is no screen for it yet: an organization's page
shows its deals in the **CRM** panel, and the totals are available to integrations at
`/api/crm/organizations/<id>/rollup`.

## The dashboard

- **Headline numbers**: people, organizations, open pipeline value and value won this month (by the
  Closed on day, in the business's time zone).
- **By stage**: count and value per stage.
- **Today**: hot deals that have gone quiet first, then your reminders due today, then the rest of
  the hot deals. Plain database work, no AI.
- **Deals to watch** and **Recent activity**.

## Weekly touches

The CRM's **Touches** tab shows, per owner, how many open deals were touched in the window (a touch
is an edit, a logged activity or a note), plus deals won in it, with a page per owner.

## Analytics

Outcomes over a window of days: wins and losses, win rate, average won and open deal size, average
days to close, activity per day and by type, how old the open deals are and which have gone stale,
and a per-owner breakdown. Days are counted in the business's time zone, so a day around a
daylight-saving change is still one calendar day.

The **Pipeline flow** section reads the stage history: time in each stage, conversion from each stage to
the next, and how long won deals took. The history starts when the CRM was installed, so the view
says how far back it really goes.
