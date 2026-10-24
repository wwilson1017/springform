/**
 * Reminders on one record: everyone's (another member's are marked with their name and have no
 * actions), and a form to set one for yourself on this record.
 */
import { useState } from 'react';
import { useJson } from '../api/useJson';
import { LoadError } from '../../shared/LoadError';
import { REMINDERS } from './reminders';
import { ReminderForm } from './ReminderForm';
import { ReminderRow } from './ReminderRow';
import type { Reminder } from './types';
import { BTN_LINK, H_SECTION, MUTED } from './ui';

export interface RemindersPanelProps {
  entityType: string;
  entityId: number;
}

export function RemindersPanel({ entityType, entityId }: RemindersPanelProps) {
  const { data, error, reload } = useJson<Reminder[]>(`${REMINDERS}/for?${new URLSearchParams({ entity_type: entityType, entity_id: String(entityId) })}`);
  const [adding, setAdding] = useState(false);

  return (
    <section aria-label="Reminders">
      <div className="mb-2 flex items-center justify-between">
        <h3 className={`${H_SECTION} mb-0`}>Reminders</h3>
        {!adding && <button type="button" className={BTN_LINK} onClick={() => setAdding(true)}>Add reminder</button>}
      </div>
      {adding && (
        <ReminderForm entity={{ entityType, entityId }} onSaved={() => { setAdding(false); reload(); }} onCancel={() => setAdding(false)} />
      )}
      {error ? <LoadError label="Couldn't load the reminders" compact onRetry={reload} />
        : !data ? <p className={MUTED}>Loading…</p>
        : data.length === 0 ? (!adding && <p className={MUTED}>No reminders on this record.</p>)
        : (
          <ul className="m-0 list-none divide-y divide-sf-line p-0">
            {data.map(r => <ReminderRow key={r.id} reminder={r} onChanged={reload} />)}
          </ul>
        )}
    </section>
  );
}
