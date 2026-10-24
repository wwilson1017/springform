/**
 * Create a reminder (optionally on a record) or edit one: title, note, when, repeat. The time is
 * picked in the browser's zone and sent as a UTC instant; the server re-anchors a repeat in the
 * owner's zone. Server refusals (a past snooze, a done reminder) are shown as sent.
 *
 * Shaped after CakeCRM's ReminderForm; Springform reminders notify their owner only, so the
 * people picker is gone.
 */
import { useId, useState } from 'react';
import { patchJson, postJson } from '../api/client';
import { REMINDERS, REPEAT_LABEL, fromLocalInput, nextHour, toLocalInput } from './reminders';
import type { Reminder, ReminderFreq } from './types';
import { BTN_PRIMARY, BTN_SECONDARY, INPUT, LABEL, errorText } from './ui';

export function ReminderForm({ reminder, entity, onSaved, onCancel }: {
  reminder?: Reminder;
  /** Attach a new reminder to this record. */
  entity?: { entityType: string; entityId: number };
  onSaved: (saved: Reminder) => void;
  onCancel: () => void;
}) {
  const id = useId();
  const [title, setTitle] = useState(reminder?.title ?? '');
  const [note, setNote] = useState(reminder?.note ?? '');
  const [due, setDue] = useState(() => toLocalInput(reminder?.due_at ?? nextHour()));
  const [repeat, setRepeat] = useState<ReminderFreq | ''>(reminder?.repeat?.freq ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!due) { setError('Pick when to be reminded.'); return; }
    setBusy(true);
    setError(null);
    const fields = { title: title.trim(), note: note.trim(), due_at: fromLocalInput(due), repeat: repeat ? { freq: repeat } : null };
    try {
      if (reminder) {
        // Only what changed: a new due_at re-arms the reminder, so an untouched time must not be sent.
        const patch: Record<string, unknown> = {};
        if (fields.title !== reminder.title) patch.title = fields.title;
        if (fields.note !== reminder.note) patch.note = fields.note;
        if (due !== toLocalInput(reminder.due_at)) patch.due_at = fields.due_at;
        if (repeat !== (reminder.repeat?.freq ?? '')) patch.repeat = fields.repeat;
        onSaved(Object.keys(patch).length ? await patchJson<Reminder>(`${REMINDERS}/${reminder.id}`, patch) : reminder);
      } else {
        onSaved(await postJson<Reminder>(REMINDERS, {
          ...fields, ...(entity ? { entity_type: entity.entityType, entity_id: entity.entityId } : {}),
        }));
      }
    } catch (err) {
      setError(errorText(err, "Couldn't save the reminder. Try again."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="flex flex-col gap-3 rounded-md border border-sf-line bg-sf-card p-3" onSubmit={e => { e.preventDefault(); void submit(); }}>
      <div>
        <label htmlFor={`${id}-title`} className={LABEL}>Remind me to</label>
        <input id={`${id}-title`} className={INPUT} required maxLength={200} autoFocus value={title} onChange={e => setTitle(e.target.value)} placeholder="Call back about the order" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor={`${id}-due`} className={LABEL}>When</label>
          <input id={`${id}-due`} type="datetime-local" className={INPUT} required value={due} onChange={e => setDue(e.target.value)} />
        </div>
        <div>
          <label htmlFor={`${id}-repeat`} className={LABEL}>Repeat</label>
          <select id={`${id}-repeat`} className={INPUT} value={repeat} onChange={e => setRepeat(e.target.value as ReminderFreq | '')}>
            <option value="">Does not repeat</option>
            {(Object.keys(REPEAT_LABEL) as ReminderFreq[]).map(f => <option key={f} value={f}>{REPEAT_LABEL[f]}</option>)}
          </select>
        </div>
      </div>
      <div>
        <label htmlFor={`${id}-note`} className={LABEL}>Note (optional)</label>
        <textarea id={`${id}-note`} className={INPUT} rows={2} maxLength={2000} value={note} onChange={e => setNote(e.target.value)} />
      </div>
      {error && <p role="alert" className="m-0 text-sm text-sf-red-text">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" className={BTN_PRIMARY} disabled={busy || !title.trim()}>{busy ? 'Saving…' : reminder ? 'Save' : 'Set reminder'}</button>
        <button type="button" className={BTN_SECONDARY} disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}
