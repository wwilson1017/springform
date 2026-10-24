/**
 * Why a deal has the touch count it has: the model's verdict on each note and activity it read,
 * with an honest banner when the verdicts no longer describe the count. The count only exists
 * with an AI provider configured; without one this says so and stops.
 */
import { useJson } from '../../../core/api/useJson';
import { LoadError } from '../../../shared/LoadError';
import { dealUrl, type TouchEvidence as Evidence } from '../api';
import { bannerCopy, coverageNote, stateLabel, summaryLine } from '../touchEvidence';
import { muted } from '../ui';
import { TouchCountPill } from './badges';

export function TouchEvidence({ dealId }: { dealId: number }) {
  const { data, error, reload } = useJson<Evidence>(`${dealUrl(dealId)}/touch-evidence`);
  if (error) return <LoadError label="Couldn't load the touch evidence" onRetry={reload} compact />;
  if (!data) return <p className={muted}>Loading…</p>;
  if (data.ai_touch_count == null && data.events.length === 0) {
    return <p className={muted}>No touch count yet. The AI works it out from notes and activity once a provider is set up.</p>;
  }
  const banner = bannerCopy(data.verdict_state, data.open);
  const coverage = coverageNote(data.truncated);
  return (
    <div className="flex flex-col gap-2 text-sm">
      <div className="flex items-center gap-2">
        {data.ai_touch_count == null ? <span className="text-sf-ink-dim">Not counted yet</span> : <TouchCountPill count={data.ai_touch_count} />}
        <button type="button" onClick={reload} className="ml-auto cursor-pointer border-0 bg-transparent p-0 text-xs text-sf-ink-dim">Refresh</button>
      </div>
      {banner && <p className="m-0 rounded bg-sf-raised px-2.5 py-2 text-xs text-sf-ink">{banner}</p>}
      {coverage && <p className="m-0 text-xs text-sf-ink-mute">{coverage}</p>}
      {data.events.length === 0 ? <p className={muted}>No notes or activity on this deal.</p> : (
        <ul className="m-0 list-none divide-y divide-sf-line p-0">
          {data.events.map((e, i) => (
            <li key={`${e.source}-${e.source_id ?? i}`} className="py-2">
              <div className="flex items-baseline gap-2">
                {/* Customer-written text: rendered as text, never as HTML. */}
                <span className="min-w-0 flex-1 break-words text-sf-ink">{e.line}</span>
                <span className={`shrink-0 text-xs ${e.state === 'touch' ? 'font-medium text-sf-green-text' : 'text-sf-ink-dim'}`}>
                  {stateLabel(e.state, data.open)}
                </span>
              </div>
              {e.reason && <p className="m-0 mt-0.5 text-xs text-sf-ink-mute italic">{e.reason}</p>}
            </li>
          ))}
        </ul>
      )}
      <p className="m-0 text-xs text-sf-ink-dim">{summaryLine(data.counted, data.evaluated, data.computed_at)}</p>
    </div>
  );
}
