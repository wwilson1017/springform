/**
 * The people ↔ organizations links of a record: on a person, their organizations; on an
 * organization, its people. Each link has a role, dates and a primary flag (a person's primary
 * organization, one per person). Link through the picker (creating inline), edit, unlink.
 */
import { useState } from 'react';
import { Link } from 'react-router';
import { confirmDialog } from '../../shared/confirm';
import { toast } from '../../shared/toast';
import { errorText, linkRecords, pageOf, unlinkRecords, updateLink, type LinkKey } from './api';
import { ContactPicker } from './ContactPicker';
import { FieldsForm, type FieldSpec } from './FieldsForm';
import { AddToggle, Star } from './PartsSections';
import type { ContactKind, ContactRef, OrganizationDetail, PersonDetail, SectionProps } from './types';
import * as ui from './ui';

interface Row {
  key: LinkKey;
  other: { kind: ContactKind; id: number; name: string };
  sub: string;
  role: string;
  is_primary: boolean;
  started_on: string | null;
  ended_on: string | null;
  archived: boolean;
}

function rowsOf(kind: ContactKind, record: SectionProps['record']): Row[] {
  if (kind === 'person') {
    return (record as PersonDetail).organizations.map(l => ({
      key: { person_id: record.id, organization_id: l.organization_id, role: l.role },
      other: { kind: 'organization', id: l.organization_id, name: l.name },
      sub: '', role: l.role, is_primary: l.is_primary, started_on: l.started_on, ended_on: l.ended_on, archived: Boolean(l.archived_at),
    }));
  }
  return (record as OrganizationDetail).people.map(l => ({
    key: { person_id: l.person_id, organization_id: record.id, role: l.role },
    other: { kind: 'person', id: l.person_id, name: l.name },
    sub: [l.title, l.email].filter(Boolean).join(' · '),
    role: l.role, is_primary: l.is_primary, started_on: l.started_on, ended_on: l.ended_on, archived: Boolean(l.archived_at),
  }));
}

const EDIT_FIELDS: FieldSpec[] = [
  { key: 'role', label: 'Role', wide: true },
  { key: 'started_on', label: 'Started', type: 'date' },
  { key: 'ended_on', label: 'Ended', type: 'date' },
];

export function LinksSection({ kind, record, reload }: SectionProps) {
  const otherKind: ContactKind = kind === 'person' ? 'organization' : 'person';
  const rows = rowsOf(kind, record);
  const [pick, setPick] = useState<ContactRef | null>(null);
  const [role, setRole] = useState('');
  const [busy, setBusy] = useState(false);

  async function write(op: () => Promise<unknown>, fail: string): Promise<boolean> {
    try {
      await op();
      reload();
      return true;
    } catch (err) {
      toast.error(errorText(err, fail));
      return false;
    }
  }

  async function add() {
    if (!pick) return;
    const key = kind === 'person'
      ? { person_id: record.id, organization_id: pick.id, role: role.trim() }
      : { person_id: pick.id, organization_id: record.id, role: role.trim() };
    setBusy(true);
    if (await write(() => linkRecords(key), "Couldn't link them.")) { setPick(null); setRole(''); }
    setBusy(false);
  }

  return (
    <div className="flex flex-col gap-3">
      {rows.length === 0
        ? <p className="m-0 text-sm text-sf-ink-dim">{kind === 'person' ? 'Not linked to an organization yet.' : 'No people linked yet.'}</p>
        : (
          <ul className="m-0 flex list-none flex-col p-0">
            {rows.map(r => <LinkRow key={`${r.other.id}:${r.role}`} row={r} personPage={kind === 'person'} write={write} />)}
          </ul>
        )}
      <AddToggle label={kind === 'person' ? 'Link an organization' : 'Link a person'}>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-[2fr_1fr_auto] sm:items-end">
          <ContactPicker kind={otherKind} label={kind === 'person' ? 'Organization' : 'Person'} value={pick} onChange={setPick} allowCreate />
          <div>
            <label htmlFor="link-role" className={ui.label}>Role</label>
            <input id="link-role" value={role} onChange={e => setRole(e.target.value)} placeholder="e.g. Buyer" className={ui.input} />
          </div>
          <button type="button" disabled={!pick || busy} onClick={() => void add()} className={ui.btnPrimary}>Link</button>
        </div>
      </AddToggle>
    </div>
  );
}

function LinkRow({ row, personPage, write }: {
  row: Row;
  personPage: boolean;
  write: (op: () => Promise<unknown>, fail: string) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(false);
  const dates = [row.started_on && `since ${row.started_on}`, row.ended_on && `until ${row.ended_on}`].filter(Boolean).join(' · ');

  async function unlink() {
    const ok = await confirmDialog({ title: 'Unlink', message: `Unlink ${row.other.name}${row.role ? ` (${row.role})` : ''}?`, confirmLabel: 'Unlink', danger: true });
    if (ok) await write(() => unlinkRecords(row.key), "Couldn't unlink them.");
  }

  if (editing) {
    return (
      <li className="border-b border-sf-line py-3 last:border-b-0">
        <p className="m-0 mb-2 text-sm text-sf-ink">{row.other.name}</p>
        <FieldsForm label={`Edit link to ${row.other.name}`} fields={EDIT_FIELDS} submitLabel="Save" onCancel={() => setEditing(false)}
          initial={{ role: row.role, started_on: row.started_on ?? '', ended_on: row.ended_on ?? '' }}
          onSubmit={async v => {
            const fields = { started_on: v.started_on || null, ended_on: v.ended_on || null, ...(v.role.trim() !== row.role ? { new_role: v.role.trim() } : {}) };
            const ok = await write(() => updateLink(row.key, fields), "Couldn't save the link.");
            if (ok) setEditing(false);
            return ok;
          }} />
      </li>
    );
  }
  return (
    <li className="flex items-start gap-2 border-b border-sf-line py-2 text-sm last:border-b-0">
      <Star on={row.is_primary} label={personPage ? 'primary organization' : `primary organization of ${row.other.name}`}
        onClick={() => void write(() => updateLink(row.key, { is_primary: true }), "Couldn't change the primary.")} />
      <div className="min-w-0 flex-1">
        <Link to={pageOf(row.other.kind, row.other.id)} className="text-sf-accent-text">{row.other.name}</Link>
        {row.archived && <span className={`${ui.chip} ml-2`}>archived</span>}
        <div className="text-xs text-sf-ink-mute">
          {[row.role || 'No role', row.sub, dates].filter(Boolean).join(' · ')}
        </div>
      </div>
      <button type="button" onClick={() => setEditing(true)} className={ui.btnLink}>Edit</button>
      <button type="button" onClick={() => void unlink()} className={`${ui.btnLink} text-sf-red-text`}>Unlink</button>
    </li>
  );
}
