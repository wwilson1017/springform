/**
 * /people/:id and /organizations/:id. A header (inline edit, archive/restore, "Merge into…"),
 * then two columns built from SECTIONS plus every app's record panels for the entity type.
 * A merged id answers `{merged_into}`; the page moves to the survivor and says so.
 *
 * Header shape lifted from CakeCRM's ContactDetailPage / CompanyDetailPage.
 */
import { Suspense, useState, type ComponentType } from 'react';
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router';
import { ApiError } from '../api/client';
import { useJson } from '../api/useJson';
import { useCoreApps } from '../apps/CoreAppsContext';
import { appBySlug, recordPanelsFor } from '../apps/registry';
import { Attachments } from '../records/Attachments';
import { RecordServices } from '../records/RecordServices';
import { Timeline } from '../records/Timeline';
import { confirmDialog } from '../../shared/confirm';
import { formatDate } from '../../shared/formatDate';
import { IconArrowLeft } from '../../shared/icons';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import {
  archiveRecord, errorText, KINDS, mergeRecords, pageOf, recordUrl, restoreRecord, splitTags, updateRecord, type RecordInput,
} from './api';
import { ContactPicker } from './ContactPicker';
import { FieldsForm, type FieldSpec } from './FieldsForm';
import { LinksSection } from './LinksSection';
import { AddressesSection, ChannelsSection } from './PartsSections';
import type {
  ContactDetail, ContactKind, ContactRef, MergedAway, OrganizationDetail, PersonDetail, SectionProps,
} from './types';
import * as ui from './ui';

interface Section {
  id: string;
  /** Omitted when the component titles its own parts (RecordServices' Fields and Reminders). */
  title?: string | ((kind: ContactKind) => string);
  column: 'main' | 'side';
  Component: ComponentType<SectionProps>;
}

// Remounts after each save, so the server's field-change entry shows up.
const TimelineSection = ({ entityType, entityId, record }: SectionProps) =>
  <Timeline key={record.updated_at} entityType={entityType} entityId={entityId} />;

/** The record page, top to bottom per column. Add a core record service here in one line. */
const SECTIONS: Section[] = [
  { id: 'links', title: k => (k === 'person' ? 'Organizations' : 'People'), column: 'main', Component: LinksSection },
  { id: 'timeline', title: 'Timeline', column: 'main', Component: TimelineSection },
  { id: 'channels', title: 'Contact details', column: 'side', Component: ChannelsSection },
  { id: 'addresses', title: 'Addresses', column: 'side', Component: AddressesSection },
  { id: 'files', title: 'Files', column: 'side', Component: Attachments },
  { id: 'services', column: 'side', Component: RecordServices },
];

const STATUS_SUGGEST = ['lead', 'active', 'inactive'];
const SOURCE_SUGGEST = ['referral', 'website', 'event', 'import', 'other'];

export default function DetailPage({ kind }: { kind: ContactKind }) {
  const { id } = useParams();
  // A fresh page per record: edit and merge state never carry over to the next id.
  return <Detail key={`${kind}:${id}`} kind={kind} id={Number(id)} />;
}

function Detail({ kind, id }: { kind: ContactKind; id: number }) {
  const { data, error, reload, setData } = useJson<ContactDetail | MergedAway>(Number.isInteger(id) ? recordUrl(kind, id) : null);
  const mergedFrom = (useLocation().state as { mergedFrom?: number[] } | null)?.mergedFrom;
  if (data && 'merged_into' in data) {
    return <Navigate to={pageOf(kind, data.merged_into)} replace state={{ mergedFrom: [id] }} />;
  }
  if (!Number.isInteger(id) || (error instanceof ApiError && error.status === 404)) {
    return <Frame kind={kind}><p className="text-sf-ink-mute">This {KINDS[kind].noun} doesn't exist.</p></Frame>;
  }
  if (error) return <Frame kind={kind}><LoadError label={`Couldn't load this ${KINDS[kind].noun}`} onRetry={reload} /></Frame>;
  if (!data) return <Frame kind={kind}><p className="text-sm text-sf-ink-dim">Loading…</p></Frame>;

  const record = data;
  const props: SectionProps = { kind, record, entityType: KINDS[kind].entityType, entityId: record.id, reload };
  return (
    <Frame kind={kind}>
      {mergedFrom && (
        <p role="status" className="mb-4 rounded-md border border-sf-line-strong bg-sf-raised px-3 py-2 text-sm text-sf-ink">
          {mergedFrom.map(m => `${kind === 'person' ? 'Person' : 'Organization'} #${m}`).join(', ')} {mergedFrom.length > 1 ? 'were' : 'was'} merged into this record.
        </p>
      )}
      <Header kind={kind} record={record} onSaved={setData} />
      <Columns kind={kind} props={props} />
    </Frame>
  );
}

function Frame({ kind, children }: { kind: ContactKind; children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-6xl px-4 py-6 md:px-8 md:py-8">
      <Link to={`/${KINDS[kind].path}`} className="mb-4 inline-flex items-center gap-1.5 text-sm text-sf-ink-dim no-underline hover:text-sf-ink">
        <IconArrowLeft size={14} aria-hidden /> {KINDS[kind].title}
      </Link>
      {children}
    </div>
  );
}

function Columns({ kind, props }: { kind: ContactKind; props: SectionProps }) {
  const { apps } = useCoreApps();
  // Panels only from apps the server lists for this user, so a member never sees a panel
  // whose API refuses them.
  const shown = new Set((apps ?? []).map(a => a.slug));
  const panels: Section[] = recordPanelsFor(props.entityType).filter(p => shown.has(p.slug)).map(p => ({
    id: `app:${p.slug}`, title: appBySlug(p.slug)?.manifest.name ?? p.slug, column: 'side', Component: p.Panel,
  }));
  const all = [...SECTIONS, ...panels];
  const column = (c: Section['column']) => all.filter(s => s.column === c).map(({ id, title, Component }) => {
    const body = (
      <Suspense fallback={<p className="m-0 text-sm text-sf-ink-dim">Loading…</p>}>
        <Component {...props} />
      </Suspense>
    );
    if (!title) return <div key={id}>{body}</div>;
    const text = typeof title === 'function' ? title(kind) : title;
    return (
      <section key={id} aria-label={text}>
        <h2 className={ui.sectionTitle}>{text}</h2>
        {body}
      </section>
    );
  });
  return (
    <div className="mt-8 grid grid-cols-1 gap-8 md:grid-cols-[minmax(0,1fr)_340px]">
      <div className="flex min-w-0 flex-col gap-8">{column('main')}</div>
      <div className="flex min-w-0 flex-col gap-8">{column('side')}</div>
    </div>
  );
}

// ── Header ──────────────────────────────────────────────────────────────────

function editFields(kind: ContactKind, ownerName: string | null): FieldSpec[] {
  const own: FieldSpec = { key: 'owner_user_id', label: 'Owner', type: 'user', options: [['', 'Nobody']], valueName: ownerName };
  const common: FieldSpec[] = [
    { key: 'status', label: 'Status', suggest: STATUS_SUGGEST },
    { key: 'source', label: 'Source', suggest: SOURCE_SUGGEST },
    own,
    { key: 'tags', label: 'Tags (comma-separated)' },
    { key: 'notes', label: 'Notes', type: 'textarea' },
  ];
  return kind === 'person'
    ? [{ key: 'name', label: 'Name', wide: true }, { key: 'given_name', label: 'Given name' }, { key: 'family_name', label: 'Family name' },
      { key: 'title', label: 'Title', wide: true }, ...common]
    : [{ key: 'name', label: 'Name', wide: true }, { key: 'domain', label: 'Domain' }, { key: 'website', label: 'Website', type: 'url' },
      { key: 'industry', label: 'Industry', wide: true }, ...common];
}

const asText = (v: unknown) => (Array.isArray(v) ? v.join(', ') : v == null ? '' : String(v));

function Header({ kind, record, onSaved }: { kind: ContactKind; record: ContactDetail; onSaved: (d: ContactDetail) => void }) {
  const navigate = useNavigate();
  const [mode, setMode] = useState<'view' | 'edit' | 'merge'>('view');
  const [busy, setBusy] = useState(false);
  const noun = KINDS[kind].noun;
  const fields = editFields(kind, record.owner_name);
  const rec = record as unknown as Record<string, unknown>;

  /** PATCH only what changed; a blank clears (null), tags go as a list. */
  async function save(values: Record<string, string>) {
    const body: RecordInput = {};
    for (const f of fields) {
      const next = values[f.key].trim();
      if (next === asText(rec[f.key])) continue;
      body[f.key] = f.key === 'tags' ? splitTags(next) : f.key === 'owner_user_id' ? (next ? Number(next) : null) : next || null;
    }
    if ('name' in body && !body.name) { toast.error('A name is required.'); return false; }
    if (Object.keys(body).length === 0) { setMode('view'); return true; }
    try {
      onSaved(await updateRecord(kind, record.id, body));
      setMode('view');
      return true;
    } catch (err) {
      toast.error(errorText(err, "Couldn't save."));
      return false;
    }
  }

  async function setArchived(archive: boolean) {
    if (archive && !await confirmDialog({
      title: `Archive ${noun}`, message: `Archive ${record.name}? It leaves lists and search, and can be restored.`, confirmLabel: 'Archive',
    })) return;
    setBusy(true);
    try {
      onSaved(await (archive ? archiveRecord(kind, record.id) : restoreRecord(kind, record.id)));
    } catch (err) {
      toast.error(errorText(err, archive ? "Couldn't archive." : "Couldn't restore."));
    }
    setBusy(false);
  }

  async function mergeInto(target: ContactRef) {
    if (!await confirmDialog({
      title: `Merge ${noun}`,
      message: `Merge ${record.name} #${record.id} into ${target.name} #${target.id}? Its contact details, links, timeline and files move there, and this record stops existing on its own. This cannot be undone.`,
      confirmLabel: 'Merge', danger: true,
    })) return;
    setBusy(true);
    try {
      await mergeRecords(kind, target.id, record.id);
      navigate(pageOf(kind, target.id), { state: { mergedFrom: [record.id] } });
    } catch (err) {
      toast.error(errorText(err, "Couldn't merge."));
      setBusy(false);
    }
  }

  if (mode === 'edit') {
    return (
      <div className={`${ui.card} p-4`}>
        <h1 className="m-0 mb-3 font-display text-xl font-medium text-sf-ink">Edit {record.name}</h1>
        <FieldsForm label={`Edit ${noun}`} fields={fields} submitLabel="Save" onCancel={() => setMode('view')} onSubmit={save}
          initial={Object.fromEntries(fields.map(f => [f.key, asText(rec[f.key])]))} />
      </div>
    );
  }

  const person = kind === 'person' ? record as PersonDetail : null;
  const org = kind === 'organization' ? record as OrganizationDetail : null;
  const primaryOrg = person?.organizations.find(o => o.is_primary);
  const facts: Array<[string, React.ReactNode]> = [
    ['Status', record.status], ['Source', record.source], ['Owner', record.owner_name ?? 'Nobody'],
  ];

  return (
    <header>
      {record.archived_at && (
        <p className="mt-0 mb-4 flex flex-wrap items-center gap-3 rounded-md border border-sf-line-strong bg-sf-raised px-3 py-2 text-sm text-sf-ink-mute">
          Archived {formatDate(record.archived_at)}. It is hidden from lists and search.
          <button type="button" disabled={busy} onClick={() => void setArchived(false)} className={ui.btnSecondary}>Restore</button>
        </p>
      )}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="m-0 font-display text-2xl font-medium break-words text-sf-ink md:text-3xl">{record.name}</h1>
          {person && (person.title || primaryOrg) && (
            <p className="mt-1 mb-0 text-sm text-sf-ink-mute">
              {person.title}{person.title && primaryOrg ? ' at ' : ''}
              {primaryOrg && <Link to={pageOf('organization', primaryOrg.organization_id)} className="text-sf-accent-text">{primaryOrg.name}</Link>}
            </p>
          )}
          {org && (org.industry || org.domain || org.website) && (
            <p className="mt-1 mb-0 text-sm text-sf-ink-mute">
              {[org.industry, org.domain].filter(Boolean).join(' · ')}
              {org.website && <>{org.industry || org.domain ? ' · ' : ''}<a href={/^https?:/i.test(org.website) ? org.website : `https://${org.website}`} target="_blank" rel="noreferrer" className="text-sf-accent-text">{org.website}</a></>}
            </p>
          )}
          {(record.email || record.phone) && (
            <p className="mt-2 mb-0 flex flex-wrap gap-x-4 gap-y-1 text-sm">
              {record.email && <a href={`mailto:${record.email}`} className="text-sf-accent-text" data-testid="header-email">{record.email}</a>}
              {record.phone && <a href={`tel:${record.phone}`} className="text-sf-accent-text">{record.phone}</a>}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => setMode('edit')} className={ui.btnSecondary}>Edit</button>
          <button type="button" disabled={busy} onClick={() => setMode(mode === 'merge' ? 'view' : 'merge')} className={ui.btnSecondary}>Merge into…</button>
          {!record.archived_at && <button type="button" disabled={busy} onClick={() => void setArchived(true)} className={ui.btnDanger}>Archive</button>}
        </div>
      </div>

      <dl className="mt-3 mb-0 flex flex-wrap gap-x-5 gap-y-1 text-sm">
        {facts.filter(([, v]) => v).map(([k, v]) => (
          <div key={k} className="flex gap-1.5"><dt className="text-sf-ink-dim">{k}</dt><dd className="m-0 text-sf-ink">{v}</dd></div>
        ))}
      </dl>
      {record.tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {record.tags.map(t => <Link key={t} to={`/${KINDS[kind].path}?tag=${encodeURIComponent(t)}`} className={`${ui.chip} no-underline`}>{t}</Link>)}
        </div>
      )}
      {record.notes && <p className={`${ui.card} mt-4 mb-0 px-4 py-3 text-sm whitespace-pre-wrap text-sf-ink-mute`}>{record.notes}</p>}

      {mode === 'merge' && (
        <div className={`${ui.card} mt-4 flex flex-col gap-2 p-4`}>
          <p className="m-0 text-sm text-sf-ink-mute">
            Pick the {noun} to keep. {record.name} is folded into it and this page moves there.
          </p>
          <div className="max-w-md">
            <ContactPicker kind={kind} label={`Merge into ${noun}`} value={null} exclude={[record.id]}
              onChange={v => { if (v) void mergeInto(v); }} />
          </div>
        </div>
      )}
    </header>
  );
}
