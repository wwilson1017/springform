/**
 * Groups of live records that share an email, phone, name (people) or domain (organizations),
 * from GET /<kind>/duplicates. Each group merges into the record the user keeps (the oldest by
 * default), after a confirm; then the page moves to the survivor.
 */
import { useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { useJson } from '../api/useJson';
import { confirmDialog } from '../../shared/confirm';
import { toast } from '../../shared/toast';
import { duplicatesUrl, errorText, KINDS, mergeRecords, pageOf } from './api';
import type { ContactKind, DuplicateGroup } from './types';
import * as ui from './ui';

const MATCH_LABEL: Record<DuplicateGroup['match_on'], string> = { email: 'Same email', phone: 'Same phone', name: 'Same name', domain: 'Same domain' };

export function DuplicatesPanel({ kind }: { kind: ContactKind }) {
  const { data: groups } = useJson<DuplicateGroup[]>(duplicatesUrl(kind));
  // A failed load hides the panel: it is a convenience beside the list, not the page's data.
  if (!groups?.length) return null;
  return (
    <details className={`${ui.card} mb-6 px-4 py-3`}>
      <summary className="cursor-pointer text-sm text-sf-ink">
        Possible duplicates <span className="text-sf-ink-dim">({groups.length})</span>
      </summary>
      <ul className="m-0 mt-3 flex list-none flex-col gap-3 p-0">
        {groups.map(g => <Group key={`${g.match_on}:${g.value}`} kind={kind} group={g} />)}
      </ul>
    </details>
  );
}

function Group({ kind, group }: { kind: ContactKind; group: DuplicateGroup }) {
  const navigate = useNavigate();
  const [keep, setKeep] = useState(group.records[0].id);
  const [busy, setBusy] = useState(false);
  const survivor = group.records.find(r => r.id === keep)!;
  const sources = group.records.filter(r => r.id !== keep);

  async function merge() {
    const ok = await confirmDialog({
      title: `Merge ${KINDS[kind].title.toLowerCase()}`,
      message: `Merge ${sources.map(s => `${s.label} #${s.id}`).join(', ')} into ${survivor.label} #${survivor.id}? `
        + 'Their contact details, links, timeline and files move to it. This cannot be undone.',
      confirmLabel: 'Merge',
      danger: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      for (const s of sources) await mergeRecords(kind, keep, s.id);
    } catch (err) {
      toast.error(errorText(err, "Couldn't merge them."));
      setBusy(false);
      return;
    }
    navigate(pageOf(kind, keep), { state: { mergedFrom: sources.map(s => s.id) } });
  }

  return (
    <li className="flex flex-col gap-2 border-t border-sf-line pt-3 first:border-t-0 first:pt-0 md:flex-row md:items-center">
      <div className="min-w-0 flex-1 text-sm">
        <span className="text-sf-ink-mute">{MATCH_LABEL[group.match_on]}: </span>
        <span className="break-all text-sf-ink">{group.value}</span>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
          {group.records.map(r => (
            <Link key={r.id} to={pageOf(kind, r.id)} className="text-sf-accent-text">{r.label} #{r.id}</Link>
          ))}
        </div>
      </div>
      <label className="flex items-center gap-2 text-xs text-sf-ink-mute">
        Keep
        <select value={keep} onChange={e => setKeep(Number(e.target.value))}
          className="rounded-md border border-sf-line-strong bg-sf-card px-2 py-1 text-sm text-sf-ink">
          {group.records.map(r => <option key={r.id} value={r.id}>{r.label} #{r.id}</option>)}
        </select>
      </label>
      <button type="button" disabled={busy} onClick={() => void merge()} className={ui.btnSecondary}>
        {busy ? 'Merging…' : 'Merge'}
      </button>
    </li>
  );
}
