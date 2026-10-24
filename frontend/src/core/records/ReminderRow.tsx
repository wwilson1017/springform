/**
 * One reminder in a list, with its owner's actions: done, snooze (presets), edit, delete. Only
 * the owner (`mine`) gets actions, and only an open or snoozed reminder can change. Every action
 * calls `onChanged` so the list refetches (done on a repeating one spawns the next).
 */
import { useState } from 'react';
import { Link } from 'react-router';
import { del, postJson } from '../api/client';
import { confirmDialog } from '../../shared/confirm';
import { formatDate } from '../../shared/formatDate';
import { toast } from '../../shared/toast';
import { REMINDERS, REPEAT_LABEL, snoozePresets } from './reminders';
import { ReminderForm } from './ReminderForm';
import type { Reminder } from './types';
import { BTN_LINK, errorText } from './ui';

const STATUS: Record<Reminder['status'], { label: string; tone: string }> = {
  open: { label: 'Open', tone: 'text-sf-ink-soft' },
  snoozed: { label: 'Snoozed', tone: 'text-sf-amber-text' },
  done: { label: 'Done', tone: 'text-sf-green-text' },
  voided: { label: 'Void', tone: 'text-sf-red-text' },
};

const SNOOZE_LABELS = snoozePresets().map(p => p.label);

export function ReminderRow({ reminder: r, onChanged, showRecord = false }: {
  reminder: Reminder;
  onChanged: () => void;
  /** Show which record it is on (the /reminders page); a record's own panel leaves it out. */
  showRecord?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const live = r.status === 'open' || r.status === 'snoozed';

  async function act(work: () => Promise<unknown>, failure: string) {
    setBusy(true);
    try {
      await work();
      onChanged();
    } catch (err) {
      toast.error(errorText(err, failure));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!await confirmDialog({ title: 'Delete reminder', message: `Delete "${r.title}"?${r.repeat ? ' This occurrence goes; if it is the latest, the series ends.' : ''}`, confirmLabel: 'Delete', danger: true })) return;
    await act(() => del(`${REMINDERS}/${r.id}`), "Couldn't delete the reminder.");
  }

  if (editing) {
    return <li className="py-2"><ReminderForm reminder={r} onSaved={() => { setEditing(false); onChanged(); }} onCancel={() => setEditing(false)} /></li>;
  }

  return (
    <li className="flex flex-col gap-1 py-2.5">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className={`text-sm ${r.status === 'done' || r.status === 'voided' ? 'text-sf-ink-soft line-through' : 'text-sf-ink'}`}>{r.title}</span>
        <span className={`text-xs ${STATUS[r.status].tone}`}>{STATUS[r.status].label}{r.fired_at && live ? ' · sent' : ''}</span>
      </div>
      <div className="flex flex-wrap gap-x-2 text-xs text-sf-ink-dim">
        <span>{formatDate(r.due_at)}</span>
        {r.repeat && <span>· {REPEAT_LABEL[r.repeat.freq]}</span>}
        {!r.mine && <span>· {r.owner.name}'s</span>}
        {showRecord && r.entity_title && r.link && <span>· <Link to={r.link} className="text-sf-accent-text">{r.entity_title}</Link></span>}
      </div>
      {r.note && <p className="m-0 whitespace-pre-wrap text-xs text-sf-ink-mute">{r.note}</p>}
      {r.status === 'voided' && r.void_reason && <p className="m-0 text-xs text-sf-ink-dim">Voided: {r.void_reason}</p>}
      {r.mine && (
        <div className="mt-0.5 flex flex-wrap items-center gap-3">
          {live && (
            <>
              <button type="button" className={BTN_LINK} disabled={busy}
                onClick={() => void act(() => postJson(`${REMINDERS}/${r.id}/done`), "Couldn't mark the reminder done.")}>Done</button>
              <label className="sr-only" htmlFor={`snooze-${r.id}`}>Snooze {r.title}</label>
              <select id={`snooze-${r.id}`} value="" disabled={busy}
                className="cursor-pointer rounded border border-sf-line-strong bg-sf-card px-1 py-0.5 font-sans text-xs text-sf-accent-text"
                onChange={e => {
                  // Computed at the click, not at render, so a page left open snoozes from now.
                  const preset = snoozePresets()[Number(e.target.value)];
                  if (preset) void act(() => postJson(`${REMINDERS}/${r.id}/snooze`, { until: preset.until }), "Couldn't snooze the reminder.");
                }}>
                <option value="">Snooze…</option>
                {SNOOZE_LABELS.map((label, i) => <option key={label} value={i}>{label}</option>)}
              </select>
              <button type="button" className={BTN_LINK} disabled={busy} onClick={() => setEditing(true)}>Edit</button>
            </>
          )}
          <button type="button" className={BTN_LINK} disabled={busy} onClick={() => void remove()}>Delete</button>
        </div>
      )}
    </li>
  );
}
