/**
 * A deal's activity log: a quick "log a call/email/meeting/note" row on top, then the entries,
 * newest first. Clicking an entry edits or deletes it. Activity is the CRM's own log (it drives
 * touch counts and staleness); free-form notes go on the timeline.
 */
import { useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { confirmDialog } from '../../../shared/confirm';
import { formatDate } from '../../../shared/formatDate';
import { toast } from '../../../shared/toast';
import { deleteActivity, logActivity, updateActivity, type Activity } from '../api';
import { btnDanger, btnPrimary, btnSecondary, input, label, muted } from '../ui';
import { Dialog } from './Dialog';

const LOG_TYPES = ['call', 'email', 'meeting', 'note'] as const;

const typeLabel = (t: string) => t.charAt(0).toUpperCase() + t.slice(1).replace(/_/g, ' ');

export function ActivityLog({ dealId, personId, activities, onChanged }: {
  dealId: number;
  personId: number | null;
  activities: Activity[];
  onChanged: () => void;
}) {
  const [kind, setKind] = useState<string>('call');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Activity | null>(null);

  async function log(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await logActivity({ activity: kind, note: note.trim(), deal_id: dealId, person_id: personId });
      setNote('');
      onChanged();
    } catch {
      toast.error("Couldn't log the activity.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <form onSubmit={log} className="flex flex-wrap gap-2">
        <label htmlFor="activity-kind" className="sr-only">Activity type</label>
        <select id="activity-kind" value={kind} onChange={e => setKind(e.target.value)} className={`${input} w-auto`}>
          {LOG_TYPES.map(t => <option key={t} value={t}>{typeLabel(t)}</option>)}
        </select>
        <label htmlFor="activity-note" className="sr-only">What happened</label>
        <input id="activity-note" value={note} onChange={e => setNote(e.target.value)} placeholder="What happened?"
          className={`${input} min-w-40 flex-1`} />
        <button type="submit" disabled={busy} className={btnPrimary}>Log</button>
      </form>
      {activities.length === 0 ? <p className={muted}>No activity yet.</p> : (
        <ul className="m-0 list-none divide-y divide-sf-line p-0">
          {activities.map(a => (
            <li key={a.id}>
              <button type="button" onClick={() => setEditing(a)}
                className="flex w-full cursor-pointer items-start gap-3 border-0 bg-transparent px-0 py-2.5 text-left hover:bg-sf-hover">
                <span className="mt-0.5 rounded bg-sf-raised px-1.5 py-0.5 text-xs text-sf-ink-mute">{typeLabel(a.activity)}</span>
                <span className="min-w-0 flex-1">
                  {a.note ? <span className="block truncate text-sm text-sf-ink">{a.note}</span> : <span className="block text-sm text-sf-ink-dim">No note</span>}
                  <span className="block text-xs text-sf-ink-dim">{a.actor_name ?? 'Someone'}{a.person_name ? ` · ${a.person_name}` : ''}</span>
                </span>
                <span className="shrink-0 text-xs text-sf-ink-dim">{formatDate(a.created_at)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {editing && <EditActivity activity={editing} onClose={() => setEditing(null)} onChanged={() => { setEditing(null); onChanged(); }} />}
    </div>
  );
}

function EditActivity({ activity, onClose, onChanged }: { activity: Activity; onClose: () => void; onChanged: () => void }) {
  const [kind, setKind] = useState(activity.activity);
  const [note, setNote] = useState(activity.note);
  const [busy, setBusy] = useState(false);
  const types = (LOG_TYPES as readonly string[]).includes(activity.activity) ? LOG_TYPES : [...LOG_TYPES, activity.activity];

  async function save() {
    setBusy(true);
    try {
      await updateActivity(activity.id, { activity: kind, note: note.trim() });
      onChanged();
    } catch {
      toast.error("Couldn't save the activity.");
      setBusy(false);
    }
  }

  async function remove() {
    if (!await confirmDialog({ title: 'Delete activity', message: 'This entry is deleted for good.', confirmLabel: 'Delete', danger: true })) return;
    setBusy(true);
    try {
      await deleteActivity(activity.id);
      onChanged();
    } catch {
      toast.error("Couldn't delete the activity.");
      setBusy(false);
    }
  }

  return (
    <Dialog title="Activity" subtitle={`${activity.actor_name ?? 'Someone'} · ${formatDate(activity.created_at)}`} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <div>
          <label htmlFor="edit-activity-kind" className={label}>Type</label>
          <select id="edit-activity-kind" value={kind} onChange={e => setKind(e.target.value)} className={input}>
            {types.map(t => <option key={t} value={t}>{typeLabel(t)}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="edit-activity-note" className={label}>Note</label>
          <textarea id="edit-activity-note" value={note} onChange={e => setNote(e.target.value)} rows={4} className={`${input} resize-y`} />
        </div>
        {activity.person_id && activity.person_name && (
          <Link to={`/people/${activity.person_id}`} className="text-sm text-sf-accent-text">{activity.person_name}</Link>
        )}
        <div className="mt-2 flex flex-wrap justify-end gap-2">
          <button type="button" onClick={() => void remove()} disabled={busy} className={`${btnDanger} mr-auto`}>Delete</button>
          <button type="button" onClick={onClose} className={btnSecondary}>Cancel</button>
          <button type="button" onClick={() => void save()} disabled={busy || !kind.trim()} className={btnPrimary}>Save</button>
        </div>
      </div>
    </Dialog>
  );
}
