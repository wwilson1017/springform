/**
 * A small form from a field list, shared by the record's edit form and the add/edit rows of
 * channels, addresses and links. Values are strings; the caller maps them to the API.
 */
import { useId, useState, type FormEvent } from 'react';
import * as ui from './ui';

export interface FieldSpec {
  key: string;
  label: string;
  type?: 'text' | 'email' | 'tel' | 'url' | 'date' | 'textarea' | 'select';
  /** For a select: [value, label] pairs. */
  options?: Array<[string, string]>;
  /** Suggestions for a free-text field. */
  suggest?: string[];
  /** Spans the whole row of the grid. */
  wide?: boolean;
}

export function FieldsForm({ fields, initial, submitLabel, onSubmit, onCancel, columns = 2, label }: {
  fields: FieldSpec[];
  initial: Record<string, string>;
  submitLabel: string;
  /** Resolves true when the save landed: an add form then clears. */
  onSubmit: (values: Record<string, string>) => Promise<boolean>;
  onCancel?: () => void;
  columns?: 1 | 2;
  /** The form's accessible name. */
  label?: string;
}) {
  const [values, setValues] = useState(initial);
  const [busy, setBusy] = useState(false);
  const uid = useId();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const ok = await onSubmit(values);
    setBusy(false);
    if (ok && !onCancel) setValues(initial);
  }

  return (
    <form aria-label={label} onSubmit={e => void submit(e)}
      className={`grid gap-2 ${columns === 2 ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-1'}`}>
      {fields.map(f => {
        const id = `${uid}-${f.key}`;
        const common = { id, value: values[f.key] ?? '', className: ui.input };
        const change = (v: string) => setValues(s => ({ ...s, [f.key]: v }));
        return (
          <div key={f.key} className={`min-w-0 ${f.wide || f.type === 'textarea' ? 'sm:col-span-2' : ''}`}>
            <label htmlFor={id} className={ui.label}>{f.label}</label>
            {f.type === 'textarea' ? <textarea {...common} rows={3} onChange={e => change(e.target.value)} />
              : f.type === 'select' ? (
                <select {...common} onChange={e => change(e.target.value)}>
                  {f.options!.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              ) : (
                <>
                  <input {...common} type={f.type ?? 'text'} list={f.suggest ? `${id}-list` : undefined} onChange={e => change(e.target.value)} />
                  {f.suggest && <datalist id={`${id}-list`}>{f.suggest.map(s => <option key={s} value={s} />)}</datalist>}
                </>
              )}
          </div>
        );
      })}
      <div className={`flex gap-2 ${columns === 2 ? 'sm:col-span-2' : ''}`}>
        <button type="submit" disabled={busy} className={ui.btnPrimary}>{busy ? 'Saving…' : submitLabel}</button>
        {onCancel && <button type="button" onClick={onCancel} className={ui.btnSecondary}>Cancel</button>}
      </div>
    </form>
  );
}
