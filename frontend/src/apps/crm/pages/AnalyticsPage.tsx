/**
 * Keyless analytics over a chosen window: win/loss, activity volume (by day and by type), deal
 * aging, per-rep numbers, and pipeline analytics (time in stage, stage conversion, velocity).
 * Every chart is one series in one hue with its numbers beside it, so nothing is colour-alone;
 * each section says plainly when it has nothing to show yet.
 */
import { useState } from 'react';
import { Link } from 'react-router';
import { useJson } from '../../../core/api/useJson';
import { LoadError } from '../../../shared/LoadError';
import { analyticsUrl, pipelineAnalyticsUrl, type Analytics, type PipelineAnalytics } from '../api';
import { stageLabel } from '../constants';
import { StatCard } from '../components/StatCard';
import { StageDot } from '../components/badges';
import { formatCents } from '../money';
import { card, field, muted, page, pageTitle, sectionTitle } from '../ui';

const WINDOWS = [30, 90, 365];
const BAR = 'var(--color-sf-ai)';

export function AnalyticsPage() {
  const [days, setDays] = useState(30);
  const a = useJson<Analytics>(analyticsUrl(days));
  const p = useJson<PipelineAnalytics>(pipelineAnalyticsUrl(Math.max(days, 7)));
  return (
    <div className={`${page} flex flex-col gap-6`}>
      <div className="flex flex-wrap items-end gap-3">
        <h1 className={`${pageTitle} mr-auto`}>Analytics</h1>
        <label htmlFor="analytics-days" className="sr-only">Window</label>
        <select id="analytics-days" value={days} onChange={e => setDays(Number(e.target.value))} className={field}>
          {WINDOWS.map(d => <option key={d} value={d}>Last {d} days</option>)}
        </select>
      </div>
      {a.error ? <LoadError label="Couldn't load analytics" onRetry={a.reload} />
        : !a.data ? <p className={muted}>Loading…</p>
        : <Sections a={a.data} />}
      <section className={`${card} p-4`}>
        <h2 className={sectionTitle}>Pipeline flow</h2>
        {p.error ? <LoadError label="Couldn't load pipeline analytics" onRetry={p.reload} compact />
          : !p.data ? <p className={muted}>Loading…</p>
          : <PipelineFlow p={p.data} />}
      </section>
    </div>
  );
}

function Sections({ a }: { a: Analytics }) {
  const wl = a.win_loss;
  const closed = wl.deals_won + wl.deals_lost;
  const dailyMax = Math.max(1, ...a.activity.daily.map(d => d.count));
  const typeMax = Math.max(1, ...a.activity.by_type.map(t => t.count));
  const ageMax = Math.max(1, ...a.aging.buckets.map(b => b.count));
  return (
    <>
      <section>
        <h2 className={sectionTitle}>Win and loss</h2>
        <div className="flex flex-wrap gap-3">
          <StatCard label="Win rate" value={wl.win_rate_pct == null ? '—' : `${Math.round(wl.win_rate_pct)}%`} sub={`${wl.deals_won} won · ${wl.deals_lost} lost`} />
          <StatCard label="Avg days to close" value={wl.avg_days_to_close == null ? '—' : `${Math.round(wl.avg_days_to_close)}d`} sub="won deals" />
          <StatCard label="Avg won deal" value={wl.avg_won_deal_cents == null ? '—' : formatCents(wl.avg_won_deal_cents)} />
          <StatCard label="Open deals" value={String(wl.open_deals)} sub={`worth ${formatCents(wl.total_pipeline_value_cents)}`} />
        </div>
        {closed > 0 ? (
          <div className="mt-3 max-w-md">
            <div className="flex h-2 gap-0.5 overflow-hidden rounded" role="img" aria-label={`${wl.deals_won} won, ${wl.deals_lost} lost`}>
              {wl.deals_won > 0 && <div style={{ flex: wl.deals_won, background: 'var(--color-crm-stage-won)' }} />}
              {wl.deals_lost > 0 && <div style={{ flex: wl.deals_lost, background: 'var(--color-crm-stage-lost)' }} />}
            </div>
            <p className="m-0 mt-1 text-xs text-sf-ink-dim">{wl.deals_won} won · {wl.deals_lost} lost</p>
          </div>
        ) : <p className={`${muted} mt-3`}>No closed deals yet.</p>}
      </section>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <section className={`${card} p-4`}>
          <h2 className={sectionTitle}>Activity · {a.activity.total} in {a.window_days} days</h2>
          {a.activity.total === 0 ? <p className={muted}>No activity logged in this window.</p> : (
            <>
              <div className="flex h-24 items-end gap-0.5" role="img" aria-label={`Activity per day over ${a.window_days} days`}>
                {a.activity.daily.map(d => (
                  <div key={d.day} title={`${d.day}: ${d.count}`} className="min-w-0 flex-1 rounded-t"
                    style={{ height: `${(d.count / dailyMax) * 100}%`, minHeight: d.count ? 2 : 0, background: BAR }} />
                ))}
              </div>
              <Bars rows={a.activity.by_type.map(t => ({ key: t.activity, label: t.activity, value: t.count }))} max={typeMax} />
            </>
          )}
        </section>
        <section className={`${card} p-4`}>
          <h2 className={sectionTitle}>Open deal age</h2>
          {a.aging.buckets.every(b => b.count === 0) ? <p className={muted}>No open deals.</p>
            : <Bars rows={a.aging.buckets.map(b => ({ key: b.label, label: `${b.label} days`, value: b.count }))} max={ageMax} />}
          <p className="m-0 mt-3 text-sm text-sf-ink-mute">
            {a.aging.stale_count} untouched for {a.stale_days}+ days. <Link to="/crm/stale" className="text-sf-accent-text">See stale deals</Link>
          </p>
        </section>
      </div>

      <section className={`${card} p-4`}>
        <h2 className={sectionTitle}>By rep</h2>
        {a.per_rep.length === 0 ? <p className={muted}>No owned deals or activity yet.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="text-left text-xs text-sf-ink-dim">
                  <th className="py-2 pr-3 font-medium">Rep</th>
                  <th className="py-2 pr-3 text-right font-medium">Open</th>
                  <th className="py-2 pr-3 text-right font-medium">Pipeline</th>
                  <th className="py-2 pr-3 text-right font-medium">Won</th>
                  <th className="py-2 pr-3 text-right font-medium">Lost</th>
                  <th className="py-2 pr-3 text-right font-medium" title="Distinct deals and people they touched in the window">Touched ({a.window_days}d)</th>
                  <th className="py-2 text-right font-medium">Activity ({a.window_days}d)</th>
                </tr>
              </thead>
              <tbody>
                {a.per_rep.map(r => (
                  <tr key={r.user_id ?? 'none'} className="border-t border-sf-line text-sf-ink">
                    <td className="py-2 pr-3">{r.name}</td>
                    <td className="py-2 pr-3 text-right">{r.deals_open}</td>
                    <td className="py-2 pr-3 text-right">{formatCents(r.open_value_cents)}</td>
                    <td className="py-2 pr-3 text-right">{r.deals_won} <span className="text-sf-ink-dim">({formatCents(r.won_value_cents)})</span></td>
                    <td className="py-2 pr-3 text-right">{r.deals_lost}</td>
                    <td className="py-2 pr-3 text-right">{r.records_touched}</td>
                    <td className="py-2 text-right text-sf-ink-mute">{r.activity_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

/** Horizontal bars, each labelled with its value: a chart that is also its own table. */
function Bars({ rows, max }: { rows: Array<{ key: string; label: string; value: number }>; max: number }) {
  return (
    <ul className="m-0 mt-3 flex list-none flex-col gap-1.5 p-0">
      {rows.map(r => (
        <li key={r.key} className="grid grid-cols-[96px_1fr_40px] items-center gap-2 text-sm" title={`${r.label}: ${r.value}`}>
          <span className="truncate text-sf-ink-mute capitalize">{r.label}</span>
          <span className="h-2 rounded-r" style={{ width: `${Math.max(r.value ? 2 : 0, (r.value / max) * 100)}%`, background: BAR }} />
          <span className="text-right text-sf-ink">{r.value}</span>
        </li>
      ))}
    </ul>
  );
}

function PipelineFlow({ p }: { p: PipelineAnalytics }) {
  if (p.time_in_stage.length === 0 && p.conversion.length === 0) {
    return <p className={muted}>Not enough stage history yet. Time in stage and conversion appear as deals move through the pipeline.</p>;
  }
  const days = (v: number | null) => (v == null ? '—' : `${Math.round(v * 10) / 10}d`);
  const pct = (rate: number | null) => (rate == null ? '' : ` (${Math.round(rate * 100)}%)`);
  return (
    <div className="flex flex-col gap-4">
      {!p.history_covers_window && p.history_since && (
        <p className="m-0 text-xs text-sf-ink-dim">Stage history starts {new Date(p.history_since).toLocaleDateString()}, so this covers {p.history_days} of {p.window_days} days.</p>
      )}
      <p className="m-0 text-sm text-sf-ink-mute">
        {p.velocity.won_in_window} won in the window{p.velocity.avg_days_to_won != null && `, ${days(p.velocity.avg_days_to_won)} on average from creation`}.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs text-sf-ink-dim">
              <th className="py-2 pr-3 font-medium">Stage</th>
              <th className="py-2 pr-3 text-right font-medium">Median time</th>
              <th className="py-2 pr-3 text-right font-medium">Average</th>
              <th className="py-2 pr-3 text-right font-medium">Entered</th>
              <th className="py-2 pr-3 text-right font-medium" title="Moved to a later stage or won">Moved on</th>
              <th className="py-2 text-right font-medium">Won</th>
            </tr>
          </thead>
          <tbody>
            {[...new Set([...p.time_in_stage.map(s => s.stage), ...p.conversion.map(c => c.stage)])].map(stage => {
              const t = p.time_in_stage.find(s => s.stage === stage);
              const c = p.conversion.find(x => x.stage === stage);
              return (
                <tr key={stage} className="border-t border-sf-line text-sf-ink">
                  <td className="py-2 pr-3"><span className="flex items-center gap-2"><StageDot stage={stage} />{stageLabel(stage)}</span></td>
                  <td className="py-2 pr-3 text-right">{days(t?.median_days ?? null)}</td>
                  <td className="py-2 pr-3 text-right text-sf-ink-mute">{days(t?.avg_days ?? null)}</td>
                  <td className="py-2 pr-3 text-right">{c?.entered ?? '—'}</td>
                  <td className="py-2 pr-3 text-right">{c ? `${c.advanced + c.won}${pct(c.progression_rate)}` : '—'}</td>
                  <td className="py-2 text-right">{c ? `${c.won}${pct(c.win_rate)}` : '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
