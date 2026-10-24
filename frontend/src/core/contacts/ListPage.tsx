/**
 * /people and /organizations: search, archived toggle, tag and (people) organization filters,
 * pages of 50, "New …" and the duplicates panel. The filters live in the URL, so back/forward
 * and a shared link keep them.
 */
import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { useJson } from '../api/useJson';
import { IconPlus } from '../../shared/icons';
import { LoadError } from '../../shared/LoadError';
import { useIsMobile } from '../../shared/useIsMobile';
import { KINDS, listUrl, pageOf, recordUrl } from './api';
import { ContactPicker } from './ContactPicker';
import { DuplicatesPanel } from './DuplicatesPanel';
import { NewRecordDialog } from './NewRecordDialog';
import type { ContactKind, ContactPage, ContactRecord, Organization, PersonRow } from './types';
import { useDebounce } from './useDebounce';
import * as ui from './ui';

interface Column {
  label: string;
  cell: (r: ContactRecord) => React.ReactNode;
}

const orgLink = (r: ContactRecord) => {
  const p = r as PersonRow;
  return p.primary_organization_id
    ? <Link to={pageOf('organization', p.primary_organization_id)} className="text-sf-accent-text">{p.primary_organization_name}</Link>
    : null;
};

const COLUMNS: Record<ContactKind, Column[]> = {
  person: [
    { label: 'Title', cell: r => (r as PersonRow).title },
    { label: 'Email', cell: r => r.email },
    { label: 'Phone', cell: r => r.phone },
    { label: 'Organization', cell: orgLink },
  ],
  organization: [
    { label: 'Domain', cell: r => (r as Organization).domain },
    { label: 'Industry', cell: r => (r as Organization).industry },
    { label: 'Email', cell: r => r.email },
    { label: 'Phone', cell: r => r.phone },
  ],
};

export default function ListPage({ kind }: { kind: ContactKind }) {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const [params, setParams] = useSearchParams();
  const [creating, setCreating] = useState(false);
  const { noun, title } = KINDS[kind];

  const q = params.get('q') ?? '';
  const tag = params.get('tag') ?? '';
  const archived = params.get('archived') === 'true';
  const orgParam = kind === 'person' ? Number(params.get('organization_id')) || undefined : undefined;
  const page = Math.max(1, Number(params.get('page')) || 1);

  /** Change some filters; any filter change goes back to page 1. Typing replaces history. */
  function update(changes: Record<string, string | null>, replace = false) {
    setParams(prev => {
      const next = new URLSearchParams(prev);
      for (const [k, v] of Object.entries(changes)) if (v) next.set(k, v); else next.delete(k);
      if (!('page' in changes)) next.delete('page');
      return next;
    }, { replace });
  }

  // Keystrokes in the search and tag boxes settle before they fetch.
  const url = useDebounce(listUrl(kind, { q, tag, archived, organization_id: orgParam, page }), 250);
  const { data, error, reload } = useJson<ContactPage<ContactRecord>>(url);
  const { data: org } = useJson<Organization>(orgParam ? recordUrl('organization', orgParam) : null);
  const filtered = Boolean(q || tag || orgParam);
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  const tagChips = (r: ContactRecord) => r.tags.map(t => (
    <button key={t} type="button" onClick={() => update({ tag: t })} title={`Only "${t}"`}
      className={`${ui.chip} mr-1 cursor-pointer border-0 hover:text-sf-ink`}>{t}</button>
  ));

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 md:px-8 md:py-8">
      <div className="mb-5 flex items-center justify-between gap-3">
        <h1 className="m-0 font-display text-2xl font-medium text-sf-ink">{title}</h1>
        <button type="button" onClick={() => setCreating(true)} className={ui.btnPrimary}>
          <IconPlus size={14} aria-hidden /> New {noun}
        </button>
      </div>

      <div className="mb-5 flex flex-wrap items-end gap-3">
        <div className="min-w-48 flex-[2]">
          <label htmlFor="contacts-q" className="sr-only">Search {title.toLowerCase()}</label>
          <input id="contacts-q" type="search" value={q} placeholder={`Search ${title.toLowerCase()}…`}
            onChange={e => update({ q: e.target.value }, true)} className={ui.input} />
        </div>
        <div className="min-w-32 flex-1">
          <label htmlFor="contacts-tag" className="sr-only">Tag</label>
          <input id="contacts-tag" value={tag} placeholder="Tag" onChange={e => update({ tag: e.target.value }, true)} className={ui.input} />
        </div>
        {kind === 'person' && (
          <div className="min-w-48 flex-[2]">
            <ContactPicker kind="organization" placeholder="Any organization"
              value={orgParam ? { id: orgParam, name: org?.name ?? `#${orgParam}` } : null}
              onChange={v => update({ organization_id: v ? String(v.id) : null })} />
          </div>
        )}
        <label className="flex items-center gap-2 py-2 text-sm text-sf-ink-mute">
          <input type="checkbox" checked={archived} onChange={e => update({ archived: e.target.checked ? 'true' : null })} className="accent-sf-accent" />
          Archived
        </label>
      </div>

      {!archived && <DuplicatesPanel kind={kind} />}

      {error ? <LoadError label={`Couldn't load ${title.toLowerCase()}`} onRetry={reload} />
        : !data ? <p className="text-sm text-sf-ink-dim">Loading…</p>
        : data.items.length === 0 ? (
          <p className="text-sm text-sf-ink-dim">
            {archived ? `No archived ${title.toLowerCase()}${filtered ? ' match these filters' : ''}.`
              : filtered ? `No ${title.toLowerCase()} match these filters.` : `No ${title.toLowerCase()} yet. Add one above.`}
          </p>
        ) : isMobile ? (
          <ul className={`${ui.card} m-0 list-none divide-y divide-sf-line p-0`}>
            {data.items.map(r => (
              <li key={r.id} className="px-4 py-3">
                <Link to={pageOf(kind, r.id)} className="font-medium text-sf-ink no-underline">{r.name}</Link>
                <div className="mt-0.5 text-xs text-sf-ink-mute">
                  {COLUMNS[kind].map(c => c.cell(r)).filter(Boolean).map((v, i) => <span key={i}>{i > 0 && ' · '}{v}</span>)}
                </div>
                {r.tags.length > 0 && <div className="mt-1">{tagChips(r)}</div>}
              </li>
            ))}
          </ul>
        ) : (
          <div className={`${ui.card} overflow-x-auto`}>
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-sf-line text-xs text-sf-ink-dim">
                  <th className="px-4 py-2 font-medium">Name</th>
                  {COLUMNS[kind].map(c => <th key={c.label} className="px-3 py-2 font-medium">{c.label}</th>)}
                  <th className="px-3 py-2 font-medium">Tags</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map(r => (
                  <tr key={r.id} onClick={e => { if (!(e.target as HTMLElement).closest('a,button')) navigate(pageOf(kind, r.id)); }}
                    className="cursor-pointer border-b border-sf-line last:border-b-0 hover:bg-sf-hover">
                    <td className="px-4 py-2.5"><Link to={pageOf(kind, r.id)} className="font-medium text-sf-ink no-underline">{r.name}</Link></td>
                    {COLUMNS[kind].map(c => <td key={c.label} className="px-3 py-2.5 text-sf-ink-mute">{c.cell(r)}</td>)}
                    <td className="px-3 py-2.5">{tagChips(r)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

      {data && data.total > data.page_size && (
        <nav aria-label="Pages" className="mt-4 flex items-center justify-end gap-3 text-sm text-sf-ink-mute">
          <span>{(page - 1) * data.page_size + 1}–{Math.min(page * data.page_size, data.total)} of {data.total}</span>
          <button type="button" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })} className={ui.btnSecondary}>Previous</button>
          <button type="button" disabled={page >= pages} onClick={() => update({ page: String(page + 1) })} className={ui.btnSecondary}>Next</button>
        </nav>
      )}

      {creating && (
        <NewRecordDialog kind={kind} onClose={() => setCreating(false)} onCreated={r => navigate(pageOf(kind, r.id))} />
      )}
    </div>
  );
}
