/**
 * /reminders: the user's own reminders, soonest first, filtered by status and a date range
 * (savable as views), with a form to add one that isn't on any record.
 */
import { useState } from 'react';
import { useJson } from '../api/useJson';
import { LoadError } from '../../shared/LoadError';
import { REMINDERS, fromLocalInput } from './reminders';
import { ReminderForm } from './ReminderForm';
import { ReminderRow } from './ReminderRow';
import { SavedViewBar } from './SavedViewBar';
import type { Reminder, ReminderStatus } from './types';
import { BTN_PRIMARY, H_PAGE, INPUT, LABEL, MUTED, PAGE } from './ui';

interface Filters {
  status: ReminderStatus | '';
  /** YYYY-MM-DD, inclusive, in the browser's zone. */
  from: string;
  to: string;
}

const NO_FILTERS: Filters = { status: '', from: '', to: '' };
// simplification: one page of the server's maximum; upgrade path: page by due_at.
const LIMIT = 200;

function listUrl(f: Filters): string {
  const q = new URLSearchParams({ limit: String(LIMIT) });
  if (f.status) q.set('status', f.status);
  if (f.from) q.set('from', fromLocalInput(f.from));
  if (f.to) {
    // `to` is exclusive on the server; the picked day is included.
    const next = new Date(`${f.to}T00:00`);
    next.setDate(next.getDate() + 1);
    q.set('to', next.toISOString());
  }
  return `${REMINDERS}?${q}`;
}

export default function RemindersPage() {
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [adding, setAdding] = useState(false);
  const { data, error, reload } = useJson<Reminder[]>(listUrl(filters));
  const set = (patch: Partial<Filters>) => setFilters(f => ({ ...f, ...patch }));

  return (
    <div className={`${PAGE} max-w-3xl`}>
      <div className="mb-6 flex items-center gap-3">
        <h1 className={`${H_PAGE} flex-1`}>Reminders</h1>
        {!adding && <button type="button" className={BTN_PRIMARY} onClick={() => setAdding(true)}>New reminder</button>}
      </div>
      {adding && (
        <div className="mb-6">
          <ReminderForm onSaved={() => { setAdding(false); reload(); }} onCancel={() => setAdding(false)} />
        </div>
      )}
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="rem-status" className={LABEL}>Status</label>
          <select id="rem-status" className={INPUT} value={filters.status} onChange={e => set({ status: e.target.value as Filters['status'] })}>
            <option value="">Any</option>
            <option value="open">Open</option>
            <option value="snoozed">Snoozed</option>
            <option value="done">Done</option>
            <option value="voided">Void</option>
          </select>
        </div>
        <div>
          <label htmlFor="rem-from" className={LABEL}>From</label>
          <input id="rem-from" type="date" className={INPUT} value={filters.from} onChange={e => set({ from: e.target.value })} />
        </div>
        <div>
          <label htmlFor="rem-to" className={LABEL}>To</label>
          <input id="rem-to" type="date" className={INPUT} value={filters.to} onChange={e => set({ to: e.target.value })} />
        </div>
        <SavedViewBar surface="core.reminders" value={filters} onChange={setFilters} schemaVersion={1} />
      </div>
      {error ? <LoadError label="Couldn't load your reminders" onRetry={reload} />
        : !data ? <p className={MUTED}>Loading…</p>
        : data.length === 0 ? <p className={MUTED}>No reminders{filters === NO_FILTERS ? ' yet' : ' match these filters'}.</p>
        : (
          <ul className="m-0 list-none divide-y divide-sf-line p-0">
            {data.map(r => <ReminderRow key={r.id} reminder={r} onChanged={reload} showRecord />)}
          </ul>
        )}
    </div>
  );
}
