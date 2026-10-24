/**
 * A record's timeline: notes, comments, field changes and system entries from
 * GET /api/core/timeline, with a composer on top. Minimal on purpose; a later wave lifts
 * CakeCRM's richer NotesThread/ActivityTimeline onto the same props.
 */
import type { FieldChange, TimelineEntry } from '../api/types';
import { useJson } from '../api/useJson';
import { formatDate } from '../../shared/formatDate';
import { LoadError } from '../../shared/LoadError';
import { NoteComposer } from './NoteComposer';

export interface TimelineProps {
  entityType: string;
  entityId: number;
}

export function Timeline({ entityType, entityId }: TimelineProps) {
  const query = new URLSearchParams({ entity_type: entityType, entity_id: String(entityId) });
  const { data: entries, error, reload } = useJson<TimelineEntry[]>(`/api/core/timeline?${query}`);

  return (
    <section aria-label="Timeline" className="flex flex-col gap-4">
      {/* Refetch rather than splice: the server owns the order. */}
      <NoteComposer entityType={entityType} entityId={entityId} onPosted={reload} />
      {error ? <LoadError label="Couldn't load the timeline" onRetry={reload} compact />
        : !entries ? <p className="m-0 text-sm text-sf-ink-dim">Loading…</p>
        : entries.length === 0 ? <p className="m-0 text-sm text-sf-ink-dim">No activity yet.</p>
        : (
          <ol className="m-0 flex list-none flex-col gap-3 p-0">
            {entries.map(entry => <Entry key={entry.id} entry={entry} />)}
          </ol>
        )}
    </section>
  );
}

function Entry({ entry }: { entry: TimelineEntry }) {
  const who = entry.author?.name ?? 'System';
  return (
    <li className="border-l-2 border-sf-line-strong pl-3">
      <div className="text-xs text-sf-ink-dim">{who} · {formatDate(entry.created_at)}</div>
      {entry.kind === 'field_change' ? (
        <ul className="m-0 list-none p-0 text-sm text-sf-ink-mute">
          {(entry.changes ?? []).map(c => <li key={c.field}>{describeChange(c)}</li>)}
        </ul>
      ) : (
        <p className={`m-0 whitespace-pre-wrap text-sm ${entry.kind === 'system' ? 'text-sf-ink-soft' : 'text-sf-ink'}`}>{entry.body}</p>
      )}
    </li>
  );
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'empty';
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

/** "changed color from red to blue" */
function describeChange(c: FieldChange): string {
  return `changed ${c.field.replace(/_/g, ' ')} from ${show(c.old)} to ${show(c.new)}`;
}
