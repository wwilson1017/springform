import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { compareTimestampsAsc } from './lib/date';
import { getReviewStatus, listProjects, listTodos, markReviewDone, type ReviewStatus } from './api';
import { STALE_DAYS } from './constants';
import { todoPath } from './menu';
import { LoadFailed, LoadingRows, TodoShell } from './TodoShell';
import type { Todo, TodoProject } from './types';
import { useTodoMeta } from './useTodoMeta';
import { useTodosChanged } from './hooks';
import { daysSince, formatAge } from './util';

interface ReviewData {
  stale: Todo[];
  stalledProjects: TodoProject[];
}

function daysAgo(n: number): string {
  if (n === 0) return 'today';
  return n === 1 ? 'yesterday' : `${n} days ago`;
}

/** Weekly review: the numbers, the stale corners, the projects quietly going
 * nowhere, and when the last review was. */
export function ReviewPage() {
  const { filters } = useTodoMeta();
  const [data, setData] = useState<ReviewData | null>(null);
  const [failed, setFailed] = useState(false);
  // The "review due" clock. Loaded on its own so a failure here never hides the
  // lists below; null while loading or after a failed read, which renders nothing.
  const [review, setReview] = useState<ReviewStatus | null>(null);
  const [marking, setMarking] = useState(false);
  const [markFailed, setMarkFailed] = useState(false);
  useEffect(() => { getReviewStatus().then(setReview).catch(() => setReview(null)); }, []);

  const markDone = () => {
    setMarking(true);
    setMarkFailed(false);
    markReviewDone()
      .then(setReview)
      .catch(() => setMarkFailed(true))
      .finally(() => setMarking(false));
  };

  const load = () => {
    Promise.all([
      // Deferred next actions included — they still cover their project.
      listTodos({ status: 'next_action', limit: 500, include_deferred: true }),
      listTodos({ status: 'waiting_for', limit: 500 }),
      listTodos({ status: 'delegated', limit: 500 }),
      listProjects('active'),
      // …and the next actions as the working list has them today, for "stale": a todo
      // put away until a later date is not stale. The server leaves those out on the
      // list's own date; sorting them here would mean guessing with this browser's.
      listTodos({ status: 'next_action', limit: 500 }),
    ]).then(([next, waiting, delegated, activeProjects, nextNow]) => {
      const stale = [...nextNow, ...waiting, ...delegated]
        .filter(t => daysSince(t.updated_at) >= STALE_DAYS)
        .sort((a, b) => compareTimestampsAsc(a.updated_at, b.updated_at));
      // "Stalled" = no NEXT ACTION — a project full of someday/waiting items
      // has open_count > 0 but still has no decided next physical step.
      // `next` is every next action, however many (`listTodos` pages), so a
      // project missing from it has none.
      const projectsWithNext = new Set(
        next.map(t => t.project_id).filter((id): id is number => id !== null),
      );
      setData({
        stale,
        stalledProjects: activeProjects.filter(p => !projectsWithNext.has(p.id)),
      });
      setFailed(false);
    }).catch(() => setFailed(true));
  };
  useEffect(load, []);
  // Review owns its own fetch, so the undo broadcast has to be taken explicitly
  // (todo-gtd #2879). Without it, undoing a project's next action from here leaves that
  // project listed under "no next action" until the page is remounted.
  useTodosChanged(load);

  const counts = filters?.status_counts;
  const tiles: { label: string; value: number; to: string }[] = counts ? [
    { label: 'Inbox', value: counts.inbox, to: todoPath('/inbox') },
    { label: 'Next', value: counts.next_action, to: todoPath('/next') },
    { label: 'Waiting', value: counts.waiting_for + counts.delegated, to: todoPath('/waiting') },
    { label: 'Someday', value: counts.someday_maybe, to: todoPath('/someday') },
    { label: 'Done', value: counts.done, to: todoPath('/done') },
  ] : [];

  return (
    <TodoShell active="review" hideQuickAdd>
      <p className="text-sm text-sf-ink-dim">
        The weekly review: empty the inbox, give every active project a next
        action, follow up on stale waiting-fors, prune someday/maybe — and
        look at that Done count.
      </p>

      {review && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          {review.review_due ? (
            <span role="status" className="rounded-full border border-sf-amber/40 bg-sf-amber/10 px-3 py-1 text-sm font-semibold text-sf-ink">
              Review due{review.days_since_review === null
                ? ' — none recorded yet'
                : ` — last one ${daysAgo(review.days_since_review)}`}
            </span>
          ) : (
            <span className="text-sm text-sf-ink-dim">
              {/* A list under a week old has had no review and is not due for one yet. */}
              {review.days_since_review === null
                ? 'No review recorded yet.'
                : `Last review ${daysAgo(review.days_since_review)}.`}
            </span>
          )}
          <button type="button" onClick={markDone} disabled={marking}
                  className="rounded-lg border border-sf-line bg-sf-card px-3 py-1 text-sm text-sf-ink transition hover:border-sf-accent/50 disabled:opacity-60">
            {marking ? 'Saving…' : 'Mark review done'}
          </button>
          {markFailed && <span role="alert" className="text-sm text-sf-ink">Could not save. Try again.</span>}
        </div>
      )}

      {counts && (
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
          {tiles.map(t => (
            <Link key={t.label} to={t.to}
                  className="rounded-xl border border-sf-line bg-sf-card p-3 text-center transition hover:border-sf-accent/50">
              <p className="font-display text-2xl font-bold text-sf-ink">{t.value}</p>
              <p className="text-xs text-sf-ink-dim">{t.label}</p>
            </Link>
          ))}
        </div>
      )}

      {failed && <div className="mt-5"><LoadFailed retry={load} /></div>}
      {!failed && data === null && <LoadingRows />}
      {data && (
        <div className="mt-6 space-y-6">
          <section>
            <h2 className="mb-2 text-xs font-display font-bold uppercase tracking-wide text-sf-ink-dim">
              Stale ({STALE_DAYS}+ days untouched)
            </h2>
            {data.stale.length === 0 ? (
              <p className="text-sm text-sf-ink-dim">Nothing stale. Clean system.</p>
            ) : (
              <div className="space-y-1">
                {data.stale.map(t => (
                  <div key={t.id}
                       className="flex items-start gap-2 rounded-lg border border-sf-line bg-sf-card px-3 py-2 text-sm">
                    {/* Wraps rather than truncates: deciding whether a stale item
                        is still worth doing needs the whole title. */}
                    <span className="min-w-0 flex-1 break-words text-sf-ink">
                      {t.title}
                    </span>
                    <span className="shrink-0 text-xs text-sf-ink-dim">{formatAge(t.updated_at)}</span>
                  </div>
                ))}
              </div>
            )}
          </section>
          <section>
            <h2 className="mb-2 text-xs font-display font-bold uppercase tracking-wide text-sf-ink-dim">
              Active projects without a next action
            </h2>
            {data.stalledProjects.length === 0 ? (
              <p className="text-sm text-sf-ink-dim">Every active project has a next action. 👌</p>
            ) : (
              <div className="space-y-1">
                {data.stalledProjects.map(p => (
                  <Link key={p.id} to={todoPath(`/projects/${p.id}`)}
                        className="block rounded-lg border border-sf-amber/40 bg-sf-amber/10 px-3 py-2 text-sm text-sf-ink hover:border-sf-accent/50">
                    {p.name}
                  </Link>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </TodoShell>
  );
}
