/**
 * Settings → Custom fields (admin): pick an entity type, then list, create, edit, archive,
 * restore and reorder its field definitions. Values are edited on the record (`CustomFields`).
 *
 * Lifted in behaviour from CakeCRM's CustomFieldSettings; the entity tabs became a picker over
 * the entity registry, archive replaces delete (the server never deletes a definition), and
 * reordering is new.
 */
import { useState } from 'react';
import { del, patchJson, postJson } from '../api/client';
import { useJson } from '../api/useJson';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { FIELD_TYPES, type EntityTypeInfo, type FieldDefinition, type FieldType } from './types';
import { BTN_LINK, BTN_PRIMARY, BTN_SECONDARY, INPUT, LABEL, MUTED, errorText } from './ui';

const DEFS = '/api/core/fields/definitions';
const TYPE_LABEL: Record<FieldType, string> = {
  text: 'Text', number: 'Number', boolean: 'Yes / no', date: 'Date', select: 'One of a list',
  multiselect: 'Several of a list', url: 'Link', user: 'Team member',
};
const hasOptions = (t: FieldType) => t === 'select' || t === 'multiselect';
/** One option per line (commas are allowed inside an option). */
const parseOptions = (text: string) => text.split('\n').map(o => o.trim()).filter(Boolean);
/** The key the server derives from a label when none is given. */
const keyFor = (label: string) => label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');

export default function CustomFieldSettings() {
  const types = useJson<EntityTypeInfo[]>('/api/core/fields/entity-types');
  const [picked, setPicked] = useState<string | null>(null);
  const entityType = picked ?? types.data?.[0]?.type ?? null;

  if (types.error) return <LoadError label="Couldn't load the record types" compact onRetry={types.reload} />;
  if (!types.data || !entityType) return <p className={MUTED}>Loading…</p>;

  return (
    <div className="flex flex-col gap-4">
      <p className={MUTED}>Add your own fields to any kind of record. Everyone sees them on the record page.</p>
      <div className="max-w-xs">
        <label htmlFor="cf-entity-type" className={LABEL}>Record type</label>
        <select id="cf-entity-type" className={INPUT} value={entityType} onChange={e => setPicked(e.target.value)}>
          {types.data.map(t => <option key={t.type} value={t.type}>{t.label_plural}</option>)}
        </select>
      </div>
      {/* key: switching type drops any open form of the previous one. */}
      <Definitions key={entityType} entityType={entityType} />
    </div>
  );
}

function Definitions({ entityType }: { entityType: string }) {
  const { data, error, reload } = useJson<FieldDefinition[]>(`${DEFS}?${new URLSearchParams({ entity_type: entityType, include_archived: 'true' })}`);
  const [editing, setEditing] = useState<number | 'new' | null>(null);
  const [busy, setBusy] = useState(false);

  if (error) return <LoadError label="Couldn't load the fields" compact onRetry={reload} />;
  if (!data) return <p className={MUTED}>Loading…</p>;
  const active = data.filter(d => !d.archived_at);
  const archived = data.filter(d => d.archived_at);

  async function run(work: () => Promise<unknown>, failure: string) {
    setBusy(true);
    try {
      await work();
      reload();
    } catch (err) {
      toast.error(errorText(err, failure));
    } finally {
      setBusy(false);
    }
  }

  /** Move a field one step; positions are rewritten 10, 20, … so ties can't stall a move. */
  const move = (index: number, step: -1 | 1) => run(async () => {
    const order = [...active];
    [order[index], order[index + step]] = [order[index + step], order[index]];
    for (const [i, d] of order.entries()) {
      if (d.position !== (i + 1) * 10) await patchJson(`${DEFS}/${d.id}`, { position: (i + 1) * 10 });
    }
  }, "Couldn't reorder the fields.");

  return (
    <div className="flex flex-col gap-3">
      {active.length === 0 && <p className={MUTED}>No fields yet.</p>}
      <ul className="m-0 list-none divide-y divide-sf-line p-0">
        {active.map((d, i) => (
          <li key={d.id} className="py-2.5">
            {editing === d.id ? (
              <DefinitionForm entityType={entityType} def={d} onDone={() => { setEditing(null); reload(); }} onCancel={() => setEditing(null)} />
            ) : (
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <div className="min-w-0 flex-1">
                  <span className="text-sm text-sf-ink">{d.label}{d.required ? ' *' : ''}</span>
                  <span className="ml-2 text-xs text-sf-ink-dim">{TYPE_LABEL[d.type]} · {d.key}</span>
                  {d.options && <div className="truncate text-xs text-sf-ink-mute">{d.options.join(', ')}</div>}
                </div>
                <div className="flex items-center gap-3">
                  <button type="button" className={BTN_LINK} disabled={busy || i === 0} aria-label={`Move ${d.label} up`} onClick={() => void move(i, -1)}>↑</button>
                  <button type="button" className={BTN_LINK} disabled={busy || i === active.length - 1} aria-label={`Move ${d.label} down`} onClick={() => void move(i, 1)}>↓</button>
                  <button type="button" className={BTN_LINK} disabled={busy} onClick={() => setEditing(d.id)}>Edit</button>
                  <button type="button" className={BTN_LINK} disabled={busy}
                    onClick={() => void run(() => del(`${DEFS}/${d.id}`), "Couldn't archive the field.")}>Archive</button>
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>
      {editing === 'new'
        ? <DefinitionForm entityType={entityType} onDone={() => { setEditing(null); reload(); }} onCancel={() => setEditing(null)} />
        : <button type="button" className={`${BTN_SECONDARY} w-fit`} onClick={() => setEditing('new')}>Add a field</button>}
      {archived.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-sf-ink-mute">Archived ({archived.length})</summary>
          <p className="m-0 mt-1 text-xs text-sf-ink-dim">Archived fields are hidden with their values. Restoring brings both back.</p>
          <ul className="m-0 mt-2 list-none p-0">
            {archived.map(d => (
              <li key={d.id} className="flex items-center gap-3 py-1.5">
                <span className="flex-1 text-sf-ink-soft">{d.label} <span className="text-xs text-sf-ink-dim">{TYPE_LABEL[d.type]} · {d.key}</span></span>
                <button type="button" className={BTN_LINK} disabled={busy}
                  onClick={() => void run(() => patchJson(`${DEFS}/${d.id}`, { archived: false }), "Couldn't restore the field.")}>Restore</button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/** Create a field (no `def`) or edit one. Type and key are fixed once created. */
function DefinitionForm({ entityType, def, onDone, onCancel }: {
  entityType: string;
  def?: FieldDefinition;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [label, setLabel] = useState(def?.label ?? '');
  const [type, setType] = useState<FieldType>(def?.type ?? 'text');
  const [key, setKey] = useState('');
  const [options, setOptions] = useState((def?.options ?? []).join('\n'));
  const [required, setRequired] = useState(def?.required ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const prefix = def ? `cf-edit-${def.id}` : 'cf-new';

  async function submit() {
    setBusy(true);
    setError(null);
    const opts = hasOptions(type) ? parseOptions(options) : null;
    try {
      if (def) {
        await patchJson(`${DEFS}/${def.id}`, { label: label.trim(), required, ...(opts ? { options: opts } : {}) });
      } else {
        await postJson(DEFS, { entity_type: entityType, label: label.trim(), type, required, options: opts, ...(key.trim() ? { key: key.trim() } : {}) });
      }
      onDone();
    } catch (err) {
      const text = errorText(err, "Couldn't save the field.");
      setError(text === 'duplicate_key' ? 'A field with that key already exists (archived fields keep their key). Pick another key.' : text);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="flex flex-col gap-3 rounded-md border border-sf-line p-3" onSubmit={e => { e.preventDefault(); void submit(); }}>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor={`${prefix}-label`} className={LABEL}>Label</label>
          <input id={`${prefix}-label`} className={INPUT} required maxLength={100} value={label} onChange={e => setLabel(e.target.value)} placeholder="e.g. Account tier" />
        </div>
        <div>
          <label htmlFor={`${prefix}-type`} className={LABEL}>Type</label>
          <select id={`${prefix}-type`} className={INPUT} value={type} disabled={!!def} onChange={e => setType(e.target.value as FieldType)}>
            {FIELD_TYPES.map(t => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
          </select>
        </div>
        {!def && (
          <div>
            <label htmlFor={`${prefix}-key`} className={LABEL}>Key (optional)</label>
            <input id={`${prefix}-key`} className={INPUT} maxLength={64} value={key} onChange={e => setKey(e.target.value)} placeholder={keyFor(label) || 'derived from the label'} />
          </div>
        )}
        {hasOptions(type) && (
          <div className="sm:col-span-2">
            <label htmlFor={`${prefix}-options`} className={LABEL}>Options, one per line</label>
            <textarea id={`${prefix}-options`} className={INPUT} rows={4} value={options} onChange={e => setOptions(e.target.value)} placeholder={'Gold\nSilver\nBronze'} />
          </div>
        )}
      </div>
      <label className="flex items-center gap-2 text-sm text-sf-ink-mute">
        <input type="checkbox" className="accent-sf-accent" checked={required} onChange={e => setRequired(e.target.checked)} />
        Required (marked with *, not enforced)
      </label>
      {error && <p role="alert" className="m-0 text-sm text-sf-red-text">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" className={BTN_PRIMARY} disabled={busy || !label.trim()}>{busy ? 'Saving…' : def ? 'Save' : 'Add field'}</button>
        <button type="button" className={BTN_SECONDARY} disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}
