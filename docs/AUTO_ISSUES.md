# Auto-issues loop: operator guide

Springform drains its open-issue backlog with the **auto-issues loop**: an orchestrator spawns
one worker per eligible GitHub issue, and each worker takes its issue to a reviewed, tested pull
request labeled **`ready-to-ship`**. Workers never merge. A separate **ship lane** merges every
`ready-to-ship` PR whose checks are green.

> The loop's engine lives in the maintainer's user-level agent skills, not in this repo. This
> document and `scripts/seed-labels.sh` are the repo-side wiring the loop expects. Forks made with
> `scripts/new-fork.sh` get the same labels and branch protection.

## Conventions

- Work starts from a GitHub issue. Branch from `master`, PR back to `master`.
- An issue someone is working by hand is self-assigned; the loop skips assigned issues.
- Respect "Blocked by: #N" lines in issue bodies: don't start an issue whose blockers aren't merged.
- Merging happens only through the ship lane. The lane is enabled per repo by a registry on the
  maintainer's machine, never by a file in this repo: repo files are PR-writable and grant nothing.

## Label vocabulary

`scripts/seed-labels.sh` creates or normalizes these (idempotent):

```bash
scripts/seed-labels.sh                 # the current repo (inferred via gh)
scripts/seed-labels.sh --repo owner/n  # an explicit repo
```

| Label | Meaning |
|-------|---------|
| `ready-to-ship` | Green by head sha, mergeable, review threads resolved. The ship lane merges it. |
| `needs-settle` | PR open but red or with unresolved threads; the settle lane fixes or answers them. |
| `no-auto-merge` | Merge needs a production write or a secret that does not exist yet. The PR body says `Needs before merge: <what, who>`. |
| `stale` | Unlabeled PR, conflicting or red, no push for 14 days. Closed at 21 days; reopen if still wanted. |
| `awaiting-answer` | Parked: waiting on a human answer to a design question. |
| `bug` | Something is broken. |
| `enhancement` | A new capability or improvement. |
| `app:<slug>` | The issue or PR concerns that app (one label per `backend/apps/*/app.json`). |

## Terminal outcomes

Every worker ends in exactly one state, printed on its last line as `OUTCOME: <state> ...`:

- **READY**: PR opened, tests green, review clean, `ready-to-ship` applied. Not merged by the worker.
- **PARKED**: needs a human answer; labeled `awaiting-answer` with the question in a comment.
- **SETTLING**: PR open but not yet mergeable; labeled `needs-settle` for the next run.
- **FAILED**: technical dead-end after bounded retries; a draft PR with what was found.
- **SKIPPED**: triage judged it non-actionable for one autonomous pass.

## Ship lane gates

Before every merge the lane checks: fresh CI green on the head sha (a red or missing check is
fixed or re-run, never merged past), base is `master`, mergeable, no `no-auto-merge` label.
Within a major version a core migration never drops or renames (a backend test lints this), so a migration
alone is not a reason to hold a merge.

## Repo prerequisites

Set once by hand (or by `scripts/new-fork.sh` for a fork); a PR cannot set them:

1. **Branch protection on `master`**: require conversation resolution and these exact check
   names from `.github/workflows/ci.yml`: `Backend`, `Frontend`, `Secret scan`, `Fork scope`.
   `Image test` runs on every PR too and can be required once it is stable.
2. **Labels**: run `scripts/seed-labels.sh` once, and again after adding an app.

> First-time contributors' fork PRs may need a maintainer to approve the workflow run before
> Actions execute; until then the checks show as pending.

## Bring-up sequence

1. A dry run on the real backlog: triage report and queue with zero GitHub mutations.
2. One worker on a throwaway issue, end to end to READY.
3. A small batch; compare cost and outcomes.
4. Only then widen the batch.
