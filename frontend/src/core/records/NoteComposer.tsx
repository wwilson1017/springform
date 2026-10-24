import { useState, type FormEvent } from 'react';
import { postJson } from '../api/client';
import type { TimelineEntry } from '../api/types';
import { toast } from '../../shared/toast';

/** Posts a note to a record's timeline. */
export function NoteComposer({ entityType, entityId, onPosted }: {
  entityType: string;
  entityId: number;
  onPosted: (entry: TimelineEntry) => void;
}) {
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      onPosted(await postJson<TimelineEntry>('/api/core/timeline', { entity_type: entityType, entity_id: entityId, body: body.trim() }));
      setBody('');
    } catch {
      toast.error("Couldn't add the note. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <label htmlFor={`note-${entityType}-${entityId}`} className="sr-only">Add a note</label>
      <textarea id={`note-${entityType}-${entityId}`} value={body} onChange={e => setBody(e.target.value)} rows={3}
        placeholder="Add a note…"
        className="box-border w-full resize-y rounded-md border border-sf-line-strong bg-sf-card px-3 py-2 text-sm text-sf-ink placeholder:text-sf-ink-dim" />
      <button type="submit" disabled={busy || !body.trim()}
        className="self-end cursor-pointer rounded-md border-0 bg-sf-accent px-4 py-1.5 text-sm font-medium text-sf-accent-ink disabled:opacity-50">
        {busy ? 'Adding…' : 'Add note'}
      </button>
    </form>
  );
}
