import { useRef, useState, type FormEvent } from 'react';
import { postJson } from '../api/client';
import type { TimelineEntry } from '../api/types';
import { toast } from '../../shared/toast';
import { MentionPicker } from './MentionPicker';
import { useMentionPicker } from './useMentionPicker';

/** Posts a note to a record's timeline; `@` mentions a teammate, who is notified. */
export function NoteComposer({ entityType, entityId, onPosted }: {
  entityType: string;
  entityId: number;
  onPosted: (entry: TimelineEntry) => void;
}) {
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  const picker = useMentionPicker(body, setBody, ref);
  const id = `note-${entityType}-${entityId}`;
  const listId = `${id}-mentions`;

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
      <label htmlFor={id} className="sr-only">Add a note</label>
      <div className="relative">
        <textarea id={id} ref={ref} value={body} rows={3} placeholder="Add a note… (@ to mention someone)"
          aria-autocomplete="list" aria-controls={picker.users.length ? listId : undefined}
          aria-activedescendant={picker.users.length ? `${listId}-${picker.index}` : undefined}
          onChange={e => { setBody(e.target.value); picker.track(e.currentTarget); }}
          onSelect={e => picker.track(e.currentTarget)}
          onKeyDown={e => { picker.onKeyDown(e); }}
          className="box-border block w-full resize-y rounded-md border border-sf-line-strong bg-sf-card px-3 py-2 text-sm text-sf-ink placeholder:text-sf-ink-dim" />
        <MentionPicker id={listId} picker={picker} />
      </div>
      <button type="submit" disabled={busy || !body.trim()}
        className="self-end cursor-pointer rounded-md border-0 bg-sf-accent px-4 py-1.5 text-sm font-medium text-sf-accent-ink disabled:opacity-50">
        {busy ? 'Adding…' : 'Add note'}
      </button>
    </form>
  );
}
