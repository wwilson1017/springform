/**
 * A record's custom fields: the admin-defined fields for its entity type with their values, and
 * an editor that saves every change in one all-or-nothing PUT. Renders nothing when the type has
 * no fields. Who may write is the server's answer: a 403 turns the section read-only.
 *
 * Lifted in behaviour from CakeCRM's CustomFieldsSection + CustomFieldInputs: only changed
 * values are sent, so a value made invalid by a later definition change never blocks a save of
 * another field.
 */
import { useId, useState } from 'react';
import { ApiError, putJson } from '../api/client';
import type { UserRef } from '../api/types';
import { useJson } from '../api/useJson';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { FieldInput } from './FieldInput';
import { displayValue, draftChanged, fromDraft, toDraft, type Draft } from './fieldValues';
import { recordChanged } from './recordEvents';
import type { FieldDefinition, FieldValue } from './types';
import { BTN_LINK, BTN_PRIMARY, BTN_SECONDARY, H_SECTION, LABEL, errorText } from './ui';

export interface CustomFieldsProps {
  entityType: string;
  entityId: number;
}

type Values = Record<string, FieldValue>;

export function CustomFields({ entityType, entityId }: CustomFieldsProps) {
  const idPrefix = useId();
  const record = new URLSearchParams({ entity_type: entityType, entity_id: String(entityId) });
  const defs = useJson<FieldDefinition[]>(`/api/core/fields/definitions?${new URLSearchParams({ entity_type: entityType })}`);
  const values = useJson<Values>(`/api/core/fields/values?${record}`);
  const needsUsers = defs.data?.some(d => d.type === 'user') ?? false;
  const users = useJson<UserRef[]>(needsUsers ? '/api/core/timeline/mentionable' : null);
  const [drafts, setDrafts] = useState<Record<string, Draft> | null>(null);
  const [readOnly, setReadOnly] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const error = defs.error ?? values.error;
  if (error) {
    return <LoadError label="Couldn't load the custom fields" compact onRetry={() => { defs.reload(); values.reload(); }} />;
  }
  if (!defs.data || !values.data || defs.data.length === 0) return null;
  const fields = defs.data;
  const current = values.data;
  const userList = users.data ?? [];
  const userName = (id: number) => userList.find(u => u.id === id)?.name ?? `User #${id}`;

  function startEdit() {
    setDrafts(Object.fromEntries(fields.map(d => [d.key, toDraft(d, current[d.key])])));
    setFormError(null);
  }

  async function save() {
    const changed: Values = {};
    for (const d of fields) {
      if (!draftChanged(d, current[d.key], drafts![d.key])) continue;
      const next = fromDraft(d, drafts![d.key]);
      if (next instanceof Error) { setFormError(next.message); return; }
      changed[d.key] = next;
    }
    if (Object.keys(changed).length === 0) { setDrafts(null); return; }
    setSaving(true);
    setFormError(null);
    try {
      values.setData(await putJson<Values>('/api/core/fields/values', { entity_type: entityType, entity_id: entityId, values: changed }));
      setDrafts(null);
      recordChanged(entityType, entityId);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setReadOnly(true);
        setDrafts(null);
        toast.error("You can't edit this record's fields.");
      } else {
        setFormError(errorText(err, "Couldn't save the fields. Try again."));
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <section aria-label="Custom fields">
      <div className="mb-3 flex items-center justify-between">
        <h3 className={`${H_SECTION} mb-0`}>Fields</h3>
        {!drafts && !readOnly && <button type="button" className={BTN_LINK} onClick={startEdit}>Edit</button>}
      </div>
      {drafts ? (
        <form className="flex flex-col gap-3" onSubmit={e => { e.preventDefault(); void save(); }}>
          {fields.map(d => {
            const id = `${idPrefix}-${d.key}`;
            return (
              <div key={d.id}>
                <label id={`${id}-label`} htmlFor={id} className={LABEL}>{d.label}{d.required ? ' *' : ''}</label>
                <FieldInput def={d} id={id} draft={drafts[d.key]} users={userList} disabled={saving}
                  onChange={next => setDrafts(prev => ({ ...prev, [d.key]: next }))} />
              </div>
            );
          })}
          {formError && <p role="alert" className="m-0 text-sm text-sf-red-text">{formError}</p>}
          <div className="flex gap-2">
            <button type="submit" disabled={saving} className={BTN_PRIMARY}>{saving ? 'Saving…' : 'Save'}</button>
            <button type="button" disabled={saving} className={BTN_SECONDARY} onClick={() => setDrafts(null)}>Cancel</button>
          </div>
        </form>
      ) : (
        <dl className="m-0 grid grid-cols-[minmax(0,10rem)_1fr] gap-x-4 gap-y-2 text-sm">
          {fields.map(d => (
            <div key={d.id} className="contents">
              <dt className="text-sf-ink-mute">{d.label}{d.required ? ' *' : ''}</dt>
              <dd className="m-0 min-w-0 break-words text-sf-ink">
                {d.type === 'url' && typeof current[d.key] === 'string'
                  ? <a href={current[d.key] as string} target="_blank" rel="noopener noreferrer" className="text-sf-accent-text">{current[d.key] as string}</a>
                  : displayValue(d, current[d.key], userName)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}
