/**
 * "New person" / "New organization": the few fields a record starts with. A person can be
 * linked to an organization (picked or created inline) in the same step. The rest is edited on
 * the record's page. Shape lifted from CakeCRM's ContactForm / CompanyForm.
 */
import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { toast } from '../../shared/toast';
import { createRecord, errorText, KINDS, linkRecords, splitTags, type RecordInput } from './api';
import { ContactPicker } from './ContactPicker';
import type { ContactDetail, ContactKind, ContactRef } from './types';
import * as ui from './ui';

const FIELDS: Record<ContactKind, Array<[key: string, label: string, type?: string]>> = {
  person: [['email', 'Email', 'email'], ['phone', 'Phone', 'tel'], ['title', 'Title']],
  organization: [['domain', 'Domain'], ['website', 'Website', 'url'], ['industry', 'Industry'], ['email', 'Email', 'email'], ['phone', 'Phone', 'tel']],
};

export function NewRecordDialog({ kind, onClose, onCreated }: {
  kind: ContactKind;
  onClose: () => void;
  onCreated: (record: ContactDetail) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [org, setOrg] = useState<ContactRef | null>(null);
  const [role, setRole] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const noun = KINDS[kind].noun;
  const set = (key: string) => (v: string) => setValues(s => ({ ...s, [key]: v }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!values.name?.trim()) { setError('A name is required.'); return; }
    setBusy(true);
    setError('');
    const body: RecordInput = {};
    for (const [k, v] of Object.entries(values)) if (v.trim()) body[k] = k === 'tags' ? splitTags(v) : v.trim();
    let created: ContactDetail;
    try {
      created = await createRecord(kind, body);
    } catch (err) {
      setError(errorText(err, `Couldn't create the ${noun}.`));
      setBusy(false);
      return;
    }
    if (org) {
      try {
        await linkRecords({ person_id: created.id, organization_id: org.id, role: role.trim(), is_primary: true });
      } catch {
        toast.error(`Created ${created.name}, but couldn't link ${org.name}.`);
      }
    }
    onCreated(created);
  }

  return (
    <Dialog title={`New ${noun}`} onClose={onClose}>
      <form onSubmit={e => void submit(e)} className="flex flex-col gap-3">
        <Field id="new-name" label="Name *" value={values.name ?? ''} onChange={set('name')} autoFocus />
        {FIELDS[kind].map(([key, text, type]) => (
          <Field key={key} id={`new-${key}`} label={text} type={type} value={values[key] ?? ''} onChange={set(key)} />
        ))}
        {kind === 'person' && (
          <div className="grid grid-cols-[2fr_1fr] gap-2">
            <ContactPicker kind="organization" label="Organization" value={org} onChange={setOrg} allowCreate placeholder="Search or create…" />
            <Field id="new-role" label="Role" value={role} onChange={setRole} />
          </div>
        )}
        <Field id="new-tags" label="Tags (comma-separated)" value={values.tags ?? ''} onChange={set('tags')} />
        {error && <p role="alert" className="m-0 text-sm text-sf-red-text">{error}</p>}
        <div className="mt-2 flex justify-end gap-2">
          <button type="button" onClick={onClose} className={ui.btnSecondary}>Cancel</button>
          <button type="submit" disabled={busy} className={ui.btnPrimary}>{busy ? 'Creating…' : `Create ${noun}`}</button>
        </div>
      </form>
    </Dialog>
  );
}

export function Field({ id, label, value, onChange, type = 'text', autoFocus }: {
  id: string; label: string; value: string; onChange: (v: string) => void; type?: string; autoFocus?: boolean;
}) {
  return (
    <div className="min-w-0">
      <label htmlFor={id} className={ui.label}>{label}</label>
      <input id={id} type={type} value={value} autoFocus={autoFocus} onChange={e => onChange(e.target.value)} className={ui.input} />
    </div>
  );
}

/** A modal card over a scrim; Escape or a click outside closes it. */
export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div onClick={onClose} className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-sf-scrim p-4 md:items-center">
      <div role="dialog" aria-modal="true" aria-label={title} onClick={e => e.stopPropagation()}
        className="w-full max-w-md rounded-lg border border-sf-line-strong bg-sf-card p-6 shadow-lg">
        <h2 className="m-0 mb-4 font-display text-xl font-medium text-sf-ink">{title}</h2>
        {children}
      </div>
    </div>
  );
}
