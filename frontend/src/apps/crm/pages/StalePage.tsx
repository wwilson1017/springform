/** Stale deals: live open deals untouched for N days (default the CRM's stale-days setting). */
import { useState } from 'react';
import { Link } from 'react-router';
import { useJson } from '../../../core/api/useJson';
import { LoadError } from '../../../shared/LoadError';
import { staleUrl, type StaleDeals } from '../api';
import { StageBadge } from '../components/badges';
import { formatCents } from '../money';
import { field, label, muted, page, pageTitle } from '../ui';

export function StalePage() {
  const [days, setDays] = useState<number | undefined>(undefined);
  const { data, error, reload } = useJson<StaleDeals>(staleUrl(days));
  return (
    <div className={`${page} flex flex-col gap-4`}>
      <div className="flex flex-wrap items-end gap-3">
        <div className="mr-auto">
          <h1 className={pageTitle}>Stale deals</h1>
          <p className="m-0 mt-1 text-sm text-sf-ink-mute">Open deals with no activity or note for {data?.stale_days ?? '…'} days or more.</p>
        </div>
        <div>
          <label htmlFor="stale-days" className={label}>Days quiet</label>
          <input id="stale-days" type="number" min={1} max={365} value={days ?? data?.stale_days ?? ''} className={`${field} w-24`}
            onChange={e => { const n = Number(e.target.value); setDays(n >= 1 && n <= 365 ? n : undefined); }} />
        </div>
      </div>
      {error ? <LoadError label="Couldn't load stale deals" onRetry={reload} />
        : !data ? <p className={muted}>Loading…</p>
        : data.deals.length === 0 ? <p className={muted}>Nothing has gone quiet. Every open deal was touched in the last {data.stale_days} days.</p>
        : (
          <>
            <ul className="m-0 list-none divide-y divide-sf-line rounded-lg border border-sf-line-strong bg-sf-card p-0">
              {data.deals.map(d => (
                <li key={d.id}>
                  <Link to={`/crm/deals/${d.id}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-sm no-underline hover:bg-sf-hover">
                    <span className="min-w-0 flex-1 truncate text-sf-ink">{d.title}</span>
                    <StageBadge stage={d.stage} />
                    <span className="text-sf-ink-mute">{formatCents(d.value_cents)}</span>
                    <span className="w-full text-xs text-sf-red-text md:w-24 md:text-right">{d.days_since_touch}d quiet</span>
                  </Link>
                </li>
              ))}
            </ul>
            {data.total_stale > data.count && <p className={muted}>Showing {data.count} of {data.total_stale}.</p>}
          </>
        )}
    </div>
  );
}
