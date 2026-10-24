/** One rep's Weekly Touches: the deals behind their number, most-touched first. */
import { Link, useParams, useSearchParams } from 'react-router';
import { useJson } from '../../../core/api/useJson';
import { formatDate } from '../../../shared/formatDate';
import { LoadError } from '../../../shared/LoadError';
import { touchDetailUrl, type WeeklyTouchDetail } from '../api';
import { StageBadge, TouchCountPill } from '../components/badges';
import { formatCents } from '../money';
import { parseOwnerParam } from '../touches';
import { muted, page, pageTitle } from '../ui';

export function TouchDetailPage() {
  const owner = parseOwnerParam(useParams().owner);
  const [search] = useSearchParams();
  const url = owner ? touchDetailUrl(owner, search.get('start') ?? undefined, search.get('end') ?? undefined) : null;
  const { data, error, reload } = useJson<WeeklyTouchDetail>(url);
  const back = <Link to="/crm/touches" className="text-sm text-sf-accent-text">← Weekly touches</Link>;

  if (!owner) return <div className={page}>{back}<p className="text-sf-ink-mute">That isn't a rep.</p></div>;
  return (
    <div className={`${page} flex flex-col gap-4`}>
      {back}
      {error ? <LoadError label="Couldn't load this rep's touches" onRetry={reload} />
        : !data ? <p className={muted}>Loading…</p>
        : (
          <>
            <div>
              <h1 className={pageTitle}>{data.rep.name || (owner === 'unassigned' ? 'Unassigned' : 'Rep')}</h1>
              <p className="m-0 mt-1 text-sm text-sf-ink-mute">{data.window.label} · {data.rep.touches} touches · {data.rep.open_deals} open deals</p>
            </div>
            {data.deals.length === 0 ? <p className={muted}>No deals touched in this window.</p> : (
              <ul className="m-0 list-none divide-y divide-sf-line rounded-lg border border-sf-line-strong bg-sf-card p-0">
                {data.deals.map(d => (
                  <li key={d.id}>
                    <Link to={`/crm/deals/${d.id}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-sm no-underline hover:bg-sf-hover">
                      <span className="min-w-0 flex-1 truncate text-sf-ink">{d.title}</span>
                      <StageBadge stage={d.stage} />
                      <TouchCountPill count={d.touch_count} />
                      <span className="text-sf-ink-mute">{formatCents(d.value_cents)}</span>
                      {d.touched_at && <span className="w-full text-xs text-sf-ink-dim md:w-auto">last {formatDate(d.touched_at)}</span>}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
            {data.truncated && <p className={muted}>Showing the first deals only.</p>}
          </>
        )}
    </div>
  );
}
