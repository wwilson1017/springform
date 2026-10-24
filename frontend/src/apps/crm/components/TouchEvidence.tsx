/**
 * Why a deal has the touch count it has: the model's verdict on each note and activity it read.
 * The count is AI-estimated and only exists with a provider configured, so with zero keys this
 * section says so and stops.
 */
import { useJson } from '../../../core/api/useJson';
import { LoadError } from '../../../shared/LoadError';
import { dealUrl, type TouchEvidence as Evidence } from '../api';
import { muted } from '../ui';

const SOURCE: Record<string, string> = { note: 'Note', activity: 'Activity', deal_notes: 'Deal notes' };

export function TouchEvidence({ dealId }: { dealId: number }) {
  const { data, error, reload } = useJson<Evidence>(`${dealUrl(dealId)}/touch-evidence`);
  if (error) return <LoadError label="Couldn't load the touch evidence" onRetry={reload} compact />;
  if (!data) return <p className={muted}>Loading…</p>;
  if (data.count == null) return <p className={muted}>No touch count yet. It is worked out by the AI after notes and activity change, once an AI provider is set up.</p>;
  const counted = data.items.filter(i => i.touch).length;
  return (
    <div className="flex flex-col gap-2">
      <p className="m-0 text-sm text-sf-ink-mute">
        {counted} of {data.items.length} entries counted as touches{!data.current && '. The deal has changed since; it will be re-counted.'}
      </p>
      <ul className="m-0 list-none divide-y divide-sf-line p-0">
        {data.items.map((v, i) => (
          <li key={`${v.source}-${v.source_id ?? i}`} className="py-2 text-sm">
            <span className={v.touch ? 'font-medium text-sf-green-text' : 'text-sf-ink-dim'}>{v.touch ? 'Touch' : 'Not a touch'}</span>
            <span className="text-sf-ink-dim"> · {SOURCE[v.source] ?? v.source}{v.changed ? ' · edited since' : ''}</span>
            {v.text && <span className="block truncate text-sf-ink">{v.text}</span>}
            {v.reason && <span className="block text-xs text-sf-ink-mute">{v.reason}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
