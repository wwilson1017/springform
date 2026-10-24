/**
 * Today: what needs you, ranked. Hot deals that have gone quiet first, then your reminders due
 * today; "Show all" adds the rest of the hot deals. The list refetches at the install's
 * midnight (`next_refresh_at`). The dashboard shows the collapsed list.
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { useJson } from '../../../core/api/useJson';
import { formatDate } from '../../../shared/formatDate';
import { LoadError } from '../../../shared/LoadError';
import { todayUrl, type Today } from '../api';
import { StageBadge } from '../components/badges';
import { collapseToday, dealEvidence, msUntilRefresh, reminderHref, type TodayReminder } from '../today';
import { btnLink, muted, page, pageTitle } from '../ui';

export function TodayPage() {
  return (
    <div className={page}>
      <h1 className={pageTitle}>Today</h1>
      <p className="m-0 mt-1 mb-4 text-sm text-sf-ink-mute">Hot deals that have gone quiet, then reminders due today.</p>
      <TodayList />
    </div>
  );
}

export function TodayList({ compact }: { compact?: boolean }) {
  const { data, error, reload } = useJson<Today>(todayUrl);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!data) return;
    const t = setTimeout(reload, msUntilRefresh(data.next_refresh_at, Date.now()));
    return () => clearTimeout(t);
  }, [data, reload]);

  if (error) return <LoadError label="Couldn't load today's list" onRetry={reload} compact />;
  if (!data) return <p className={muted}>Loading…</p>;
  if (data.items.length === 0) return <p className={muted}>Nothing needs you today.</p>;
  const { visible, hiddenCount } = collapseToday(data.items, expanded);

  return (
    <div className="flex flex-col gap-2">
      {visible.length === 0 && <p className={muted}>Nothing urgent.</p>}
      <ul className="m-0 list-none divide-y divide-sf-line p-0">
        {visible.map(item => {
          if (item.kind === 'deal' && item.deal) {
            const d = item.deal;
            return (
              <li key={`d${d.id}`}>
                <Link to={`/crm/deals/${d.id}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 text-sm no-underline">
                  <span className="min-w-0 flex-1 truncate text-sf-ink">{d.title}</span>
                  <StageBadge stage={d.stage} />
                  <span className="w-full text-xs text-sf-ink-dim md:w-auto">{item.reason} · {dealEvidence(d.last_activity_at, d.value_cents, d.currency)}</span>
                </Link>
              </li>
            );
          }
          const r = item.reminder as TodayReminder | null | undefined;
          if (!r) return null;
          return (
            <li key={`r${r.id}`}>
              <Link to={reminderHref(r)} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 text-sm no-underline">
                <span className="rounded bg-sf-raised px-1.5 py-0.5 text-xs text-sf-ink-mute">Reminder</span>
                <span className="min-w-0 flex-1 truncate text-sf-ink">{r.title}</span>
                <span className="text-xs text-sf-ink-dim">{r.fired_at ? 'sent' : formatDate(r.due_at)}</span>
              </Link>
            </li>
          );
        })}
      </ul>
      {compact && hiddenCount > 0 && (
        <Link to="/crm/today" className="text-sm text-sf-accent-text">{hiddenCount} more on Today</Link>
      )}
      {!compact && hiddenCount > 0 && (
        <button type="button" onClick={() => setExpanded(e => !e)} className={`${btnLink} self-start`}>
          {expanded ? 'Show fewer' : `Show all (${hiddenCount} more)`}
        </button>
      )}
    </div>
  );
}
