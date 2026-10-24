/**
 * Weekly Touches: per rep, how many AI-counted touches their open deals got in a window (the
 * last 7 days by default, or a custom range), and how many open deals they hold. Each row opens
 * the rep's deals. Counts need an AI provider; without one the list is empty and says why.
 */
import { useState } from 'react';
import { Link } from 'react-router';
import { useJson } from '../../../core/api/useJson';
import { LoadError } from '../../../shared/LoadError';
import { touchesUrl, type WeeklyTouches } from '../api';
import { touchDetailPath } from '../touches';
import { btnSecondary, input, label, muted, page, pageTitle } from '../ui';

export function TouchesPage() {
  const [applied, setApplied] = useState<{ start: string; end: string } | null>(null);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const { data, error, reload } = useJson<WeeklyTouches>(touchesUrl(applied?.start, applied?.end));

  return (
    <div className={`${page} flex flex-col gap-4`}>
      <div>
        <h1 className={pageTitle}>Weekly touches</h1>
        <p className="m-0 mt-1 text-sm text-sf-ink-mute">{data ? `${data.window.label} · ${data.window.start} to ${data.window.end}` : ' '}</p>
      </div>
      <form className="flex flex-wrap items-end gap-2" onSubmit={e => { e.preventDefault(); if (start && end) setApplied({ start, end }); }}>
        <div>
          <label htmlFor="touch-start" className={label}>From</label>
          <input id="touch-start" type="date" value={start} onChange={e => setStart(e.target.value)} className={input} />
        </div>
        <div>
          <label htmlFor="touch-end" className={label}>To</label>
          <input id="touch-end" type="date" value={end} min={start} onChange={e => setEnd(e.target.value)} className={input} />
        </div>
        <button type="submit" disabled={!start || !end || end < start} className={btnSecondary}>Apply</button>
        {applied && <button type="button" onClick={() => { setApplied(null); setStart(''); setEnd(''); }} className={btnSecondary}>Last 7 days</button>}
      </form>
      {error ? <LoadError label="Couldn't load weekly touches" onRetry={reload} />
        : !data ? <p className={muted}>Loading…</p>
        : data.reps.length === 0 ? <p className={muted}>No touches counted in this window. Touch counts are worked out by the AI from notes and activity, once an AI provider is set up.</p>
        : (
          <>
            <p className="m-0 text-sm text-sf-ink-mute">{data.total_touches} touches across {data.total_open_deals} open deals.</p>
            <ul className="m-0 list-none divide-y divide-sf-line rounded-lg border border-sf-line-strong bg-sf-card p-0">
              {data.reps.map(r => (
                <li key={r.user_id ?? 'unassigned'}>
                  <Link to={touchDetailPath(r.user_id, data.window)} className="flex items-center gap-3 px-4 py-3 text-sm no-underline hover:bg-sf-hover">
                    <span className={`flex-1 ${r.user_id === null ? 'text-sf-ink-mute' : 'text-sf-ink'}`}>{r.name}</span>
                    <span className="text-sf-ink">{r.touches} touch{r.touches === 1 ? '' : 'es'}</span>
                    <span className="w-24 text-right text-sf-ink-dim">{r.open_deals} open</span>
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}
    </div>
  );
}
