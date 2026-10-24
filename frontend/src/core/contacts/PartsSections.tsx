/**
 * A record's contact channels (email, phone, url, other) and addresses: add, edit, remove, and
 * a star for the primary. One primary per kind of channel and one address per record; the
 * server promotes the next row when the primary goes, and mirrors the primary email and phone
 * onto the record, so every write reloads the record.
 */
import { useState } from 'react';
import { confirmDialog } from '../../shared/confirm';
import { toast } from '../../shared/toast';
import { addPart, deletePart, errorText, updatePart } from './api';
import { FieldsForm, type FieldSpec } from './FieldsForm';
import type { Address, Channel, ChannelKind, SectionProps } from './types';
import * as ui from './ui';

type Part = 'channels' | 'addresses';

/** Run a write, then reload the record; false (and a toast) when it was refused. */
async function write(op: Promise<unknown>, fail: string, reload: () => void): Promise<boolean> {
  try {
    await op;
    reload();
    return true;
  } catch (err) {
    toast.error(errorText(err, fail));
    return false;
  }
}

const blankToNull = (v: Record<string, string>) =>
  Object.fromEntries(Object.entries(v).map(([k, s]) => [k, s.trim() || null]));

// ── Channels ────────────────────────────────────────────────────────────────

const CHANNEL_KINDS: Array<[ChannelKind, string]> = [['email', 'Email'], ['phone', 'Phone'], ['url', 'Website'], ['other', 'Other']];
const CHANNEL_FIELDS: FieldSpec[] = [
  { key: 'kind', label: 'Kind', type: 'select', options: CHANNEL_KINDS },
  { key: 'label', label: 'Label', suggest: ['work', 'home', 'mobile', 'personal'] },
  { key: 'value', label: 'Value', wide: true },
];

function channelHref(c: Channel): string | undefined {
  if (c.kind === 'email') return `mailto:${c.value}`;
  if (c.kind === 'phone') return `tel:${c.value.replace(/[^\d+]/g, '')}`;
  if (c.kind === 'url') return /^https?:\/\//i.test(c.value) ? c.value : `https://${c.value}`;
  return undefined;
}

export function ChannelsSection({ kind, record, reload }: SectionProps) {
  const add = (v: Record<string, string>) => {
    if (!v.value.trim()) { toast.error('Enter a value.'); return Promise.resolve(false); }
    return write(addPart('channels', kind, record.id, blankToNull(v)), "Couldn't add it.", reload);
  };
  return (
    <div className="flex flex-col gap-3">
      {record.channels.length === 0 ? <p className="m-0 text-sm text-sf-ink-dim">No email, phone or website yet.</p> : (
        <ul className="m-0 flex list-none flex-col p-0">
          {record.channels.map(c => (
            <PartRow key={c.id} part="channels" row={c} reload={reload} fields={CHANNEL_FIELDS}
              primaryLabel={`primary ${CHANNEL_KINDS.find(k => k[0] === c.kind)![1].toLowerCase()}`}
              initial={{ kind: c.kind, label: c.label ?? '', value: c.value }}>
              <div className="text-xs text-sf-ink-dim">{CHANNEL_KINDS.find(k => k[0] === c.kind)![1]}{c.label ? ` · ${c.label}` : ''}</div>
              {channelHref(c)
                ? <a href={channelHref(c)} target={c.kind === 'url' ? '_blank' : undefined} rel="noreferrer" className="break-all text-sf-accent-text">{c.value}</a>
                : <span className="break-all text-sf-ink">{c.value}</span>}
            </PartRow>
          ))}
        </ul>
      )}
      <AddToggle label="Add email, phone or website">
        <FieldsForm label="Add a contact detail" fields={CHANNEL_FIELDS} initial={{ kind: 'email', label: '', value: '' }} submitLabel="Add" onSubmit={add} />
      </AddToggle>
    </div>
  );
}

// ── Addresses ───────────────────────────────────────────────────────────────

const ADDRESS_FIELDS: FieldSpec[] = [
  { key: 'kind', label: 'Kind', suggest: ['work', 'home', 'billing', 'shipping'] },
  { key: 'line1', label: 'Street', wide: true },
  { key: 'line2', label: 'Line 2', wide: true },
  { key: 'city', label: 'City' },
  { key: 'region', label: 'State / region' },
  { key: 'postal_code', label: 'Postal code' },
  { key: 'country', label: 'Country' },
];
const ADDRESS_KEYS = ADDRESS_FIELDS.map(f => f.key) as Array<keyof Address>;
const BLANK_ADDRESS = Object.fromEntries(ADDRESS_KEYS.map(k => [k, '']));

export function AddressesSection({ kind, record, reload }: SectionProps) {
  const add = (v: Record<string, string>) => {
    if (!Object.values(v).some(s => s.trim())) { toast.error('Enter an address.'); return Promise.resolve(false); }
    return write(addPart('addresses', kind, record.id, blankToNull(v)), "Couldn't add the address.", reload);
  };
  return (
    <div className="flex flex-col gap-3">
      {record.addresses.length === 0 ? <p className="m-0 text-sm text-sf-ink-dim">No addresses yet.</p> : (
        <ul className="m-0 flex list-none flex-col p-0">
          {record.addresses.map(a => (
            <PartRow key={a.id} part="addresses" row={a} reload={reload} fields={ADDRESS_FIELDS} primaryLabel="primary address"
              initial={Object.fromEntries(ADDRESS_KEYS.map(k => [k, String(a[k] ?? '')]))}>
              {a.kind && <div className="text-xs text-sf-ink-dim">{a.kind}</div>}
              <div className="whitespace-pre-line text-sf-ink">{formatAddress(a)}</div>
            </PartRow>
          ))}
        </ul>
      )}
      <AddToggle label="Add an address">
        <FieldsForm label="Add an address" fields={ADDRESS_FIELDS} initial={BLANK_ADDRESS} submitLabel="Add address" onSubmit={add} />
      </AddToggle>
    </div>
  );
}

function formatAddress(a: Address): string {
  const cityLine = [a.city, [a.region, a.postal_code].filter(Boolean).join(' ')].filter(Boolean).join(', ');
  return [a.line1, a.line2, cityLine, a.country].filter(Boolean).join('\n');
}

// ── Shared row ──────────────────────────────────────────────────────────────

function PartRow({ part, row, reload, fields, initial, primaryLabel, children }: {
  part: Part;
  row: Channel | Address;
  reload: () => void;
  fields: FieldSpec[];
  initial: Record<string, string>;
  primaryLabel: string;
  children: React.ReactNode;
}) {
  const [editing, setEditing] = useState(false);

  async function remove() {
    if (!await confirmDialog({ title: 'Remove', message: `Remove this ${part === 'channels' ? 'contact detail' : 'address'}?`, confirmLabel: 'Remove', danger: true })) return;
    await write(deletePart(part, row.id), "Couldn't remove it.", reload);
  }

  if (editing) {
    return (
      <li className="border-b border-sf-line py-3 last:border-b-0">
        <FieldsForm label="Edit" fields={fields} initial={initial} submitLabel="Save" onCancel={() => setEditing(false)}
          onSubmit={async v => {
            const ok = await write(updatePart(part, row.id, blankToNull(v)), "Couldn't save it.", reload);
            if (ok) setEditing(false);
            return ok;
          }} />
      </li>
    );
  }
  return (
    <li className="flex items-start gap-2 border-b border-sf-line py-2 text-sm last:border-b-0">
      <Star on={row.is_primary} label={primaryLabel}
        onClick={() => void write(updatePart(part, row.id, { is_primary: true }), "Couldn't change the primary.", reload)} />
      <div className="min-w-0 flex-1">{children}</div>
      <button type="button" onClick={() => setEditing(true)} className={ui.btnLink}>Edit</button>
      <button type="button" onClick={() => void remove()} className={`${ui.btnLink} text-sf-red-text`}>Remove</button>
    </li>
  );
}

/** Filled when this row is the primary; clicking an empty star makes the row primary. */
export function Star({ on, label, onClick }: { on: boolean; label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} disabled={on} aria-pressed={on}
      aria-label={on ? `The ${label}` : `Make it the ${label}`} title={on ? `The ${label}` : `Make it the ${label}`}
      className={`cursor-pointer border-0 bg-transparent p-0 text-base leading-5 disabled:cursor-default ${on ? 'text-sf-amber-text' : 'text-sf-ink-dim hover:text-sf-amber-text'}`}>
      {on ? '★' : '☆'}
    </button>
  );
}

/** An add form behind a "+ Add …" link, so a section reads as a list first. */
export function AddToggle({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  if (!open) return <button type="button" onClick={() => setOpen(true)} className={`${ui.btnLink} w-fit text-sm`}>+ {label}</button>;
  return (
    <div className="flex flex-col gap-2 rounded-md bg-sf-raised p-3">
      {children}
      <button type="button" onClick={() => setOpen(false)} className={`${ui.btnLink} w-fit text-sf-ink-mute`}>Close</button>
    </div>
  );
}
