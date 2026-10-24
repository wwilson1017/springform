/**
 * A record's timeline: notes, comments, field changes and system entries from
 * GET /api/core/timeline (newest first, pages of 50 via `?before=<id>`), with a composer on top.
 * Minimal on purpose; a later wave lifts CakeCRM's richer NotesThread/ActivityTimeline onto the
 * same props.
 */
import { useEffect, useState } from 'react';
import { fetchJson } from '../api/client';
import type { TimelineEntry } from '../api/types';
import { useJson } from '../api/useJson';
import { formatDate } from '../../shared/formatDate';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { useUserNames } from '../../shared/users';
import { describeChange, holdsUser, type FieldInfo } from './changeText';
import { bodySegments } from './mentions';
import { NoteComposer } from './NoteComposer';
import { onRecordChanged } from './recordEvents';
import type { FieldDefinition } from './types';

const PAGE = 50;

// Custom field labels and types by key, one fetch per entity type for the page's life (archived
// fields included, so an old change still reads by its label). A key added since shows humanized.
const fieldCache = new Map<string, Promise<FieldInfo>>();

function fieldInfo(entityType: string): Promise<FieldInfo> {
  let info = fieldCache.get(entityType);
  if (!info) {
    const url = `/api/core/fields/definitions?${new URLSearchParams({ entity_type: entityType, include_archived: 'true' })}`;
    info = fetchJson<FieldDefinition[]>(url).then(
      defs => Object.fromEntries(defs.map(d => [d.key, { label: d.label, type: d.type }])),
      () => { fieldCache.delete(entityType); return {}; },
    );
    fieldCache.set(entityType, info);
  }
  return info;
}

/** The fields, fetched only once a custom field change is on screen. */
function useFieldInfo(entityType: string, needed: boolean): FieldInfo {
  const [loaded, setLoaded] = useState<{ entityType: string; fields: FieldInfo } | null>(null);
  useEffect(() => {
    if (!needed) return;
    let live = true;
    void fieldInfo(entityType).then(fields => { if (live) setLoaded({ entityType, fields }); });
    return () => { live = false; };
  }, [entityType, needed]);
  return loaded?.entityType === entityType ? loaded.fields : {};
}

export interface TimelineProps {
  entityType: string;
  entityId: number;
}

export function Timeline({ entityType, entityId }: TimelineProps) {
  const base = `/api/core/timeline?${new URLSearchParams({ entity_type: entityType, entity_id: String(entityId) })}`;
  const { data: first, error, reload } = useJson<TimelineEntry[]>(`${base}&limit=${PAGE}`);
  // Older pages, tagged with the record they belong to so a prop change can't show stale ones.
  const [older, setOlder] = useState<{ base: string; entries: TimelineEntry[]; more: boolean } | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const olderHere = older?.base === base ? older : null;
  const entries = first && [...first, ...(olderHere?.entries ?? [])];
  const more = olderHere ? olderHere.more : first?.length === PAGE;
  const changes = entries?.flatMap(e => e.changes ?? []) ?? [];
  const fields = useFieldInfo(entityType, changes.some(c => c.field.startsWith('field.')));
  const userName = useUserNames(changes.filter(c => holdsUser(c.field, fields))
    .flatMap(c => [c.old, c.new]).filter((v): v is number => typeof v === 'number'));

  // A custom field save on this record writes a change entry; show it.
  useEffect(() => onRecordChanged((type, id) => {
    if (type === entityType && id === entityId) { setOlder(null); reload(); }
  }), [entityType, entityId, reload]);

  async function showOlder() {
    const last = entries![entries!.length - 1];
    setLoadingOlder(true);
    try {
      const page = await fetchJson<TimelineEntry[]>(`${base}&before=${last.id}&limit=${PAGE}`);
      setOlder({ base, entries: [...(olderHere?.entries ?? []), ...page], more: page.length === PAGE });
    } catch {
      toast.error("Couldn't load older activity.");
    } finally {
      setLoadingOlder(false);
    }
  }

  // Refetch rather than splice: the server owns the order. Older pages are dropped because the
  // new entry shifts every page boundary by one.
  const onPosted = () => { setOlder(null); reload(); };

  return (
    <section aria-label="Timeline" className="flex flex-col gap-4">
      <NoteComposer entityType={entityType} entityId={entityId} onPosted={onPosted} />
      {error ? <LoadError label="Couldn't load the timeline" onRetry={reload} compact />
        : !entries ? <p className="m-0 text-sm text-sf-ink-dim">Loading…</p>
        : entries.length === 0 ? <p className="m-0 text-sm text-sf-ink-dim">No activity yet.</p>
        : (
          <ol className="m-0 flex list-none flex-col gap-3 p-0">
            {entries.map(entry => <Entry key={entry.id} entry={entry} fields={fields} userName={userName} />)}
          </ol>
        )}
      {more && (
        <button type="button" disabled={loadingOlder} onClick={() => void showOlder()}
          className="w-fit cursor-pointer rounded-md border border-sf-line-strong bg-transparent px-3 py-1.5 font-sans text-sm text-sf-ink-mute hover:bg-sf-hover disabled:opacity-50">
          {loadingOlder ? 'Loading…' : 'Show older'}
        </button>
      )}
    </section>
  );
}

function Entry({ entry, fields, userName }: { entry: TimelineEntry; fields: FieldInfo; userName: (id: number) => string }) {
  const who = entry.author?.name ?? 'System';
  return (
    <li className="border-l-2 border-sf-line-strong pl-3">
      <div className="text-xs text-sf-ink-dim">{who} · {formatDate(entry.created_at)}</div>
      {entry.kind === 'field_change' ? (
        <ul className="m-0 list-none p-0 text-sm text-sf-ink-mute">
          {(entry.changes ?? []).map(c => <li key={c.field}>{describeChange(c, fields, userName)}</li>)}
        </ul>
      ) : (
        <p className={`m-0 whitespace-pre-wrap text-sm ${entry.kind === 'system' ? 'text-sf-ink-soft' : 'text-sf-ink'}`}>
          {bodySegments(entry.body ?? '').map((seg, i) => typeof seg === 'string' ? seg : (
            <span key={i} title={`Mentioned ${seg.name}`} className="rounded bg-sf-accent-soft px-1 font-medium text-sf-accent-text">@{seg.name}</span>
          ))}
        </p>
      )}
    </li>
  );
}
