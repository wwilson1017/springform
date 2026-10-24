/**
 * Stage criteria: what a deal must show to enter each stage, a summary plus a checklist.
 * Everyone reads them on the board; admins edit them here or reset a stage to the standard set.
 */
import { useState } from 'react';
import { ApiError } from '../../../core/api/client';
import { useJson } from '../../../core/api/useJson';
import { confirmDialog } from '../../../shared/confirm';
import { LoadError } from '../../../shared/LoadError';
import { toast } from '../../../shared/toast';
import { resetStageCriteria, saveStageCriteria, stageCriteriaUrl, type StageCriteria } from '../api';
import { stageLabel } from '../constants';
import { btnLink, btnPrimary, btnSecondary, input, label, muted } from '../ui';
import { StageDot } from './badges';

const MAX_ITEMS = 30;

export function StageCriteriaEditor() {
  const { data, error, reload, setData } = useJson<StageCriteria[]>(stageCriteriaUrl);
  const [open, setOpen] = useState<string | null>(null);
  if (error) return <LoadError label="Couldn't load the stage criteria" onRetry={reload} compact />;
  if (!data) return <p className={muted}>Loading…</p>;
  const replace = (c: StageCriteria) => setData(data.map(x => (x.stage === c.stage ? c : x)));
  return (
    <ul className="m-0 list-none divide-y divide-sf-line p-0">
      {data.map(c => (
        <li key={c.stage} className="py-2">
          <button type="button" onClick={() => setOpen(open === c.stage ? null : c.stage)} aria-expanded={open === c.stage}
            className="flex w-full cursor-pointer items-center gap-2 border-0 bg-transparent p-0 text-left text-sm text-sf-ink">
            <StageDot stage={c.stage} />
            <span className="font-medium">{stageLabel(c.stage)}</span>
            <span className="text-xs text-sf-ink-dim">{c.is_default ? 'standard' : 'custom'} · {c.checklist.length} items</span>
          </button>
          {open === c.stage && <CriteriaForm key={c.updated_at ?? 'std'} criteria={c} onSaved={replace} />}
        </li>
      ))}
    </ul>
  );
}

function CriteriaForm({ criteria, onSaved }: { criteria: StageCriteria; onSaved: (c: StageCriteria) => void }) {
  const [summary, setSummary] = useState(criteria.summary);
  const [items, setItems] = useState(criteria.checklist);
  const [busy, setBusy] = useState(false);
  const trimmed = items.map(s => s.trim());
  const valid = summary.trim() !== '' && trimmed.length > 0 && trimmed.every(Boolean);
  const name = stageLabel(criteria.stage);

  async function run(write: () => Promise<StageCriteria>, done: string) {
    setBusy(true);
    try {
      onSaved(await write());
      toast.success(done);
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.detail : "Couldn't save the criteria.");
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    const ok = await confirmDialog({
      title: `Reset ${name} to the standard criteria?`,
      message: 'Your own summary and checklist for this stage are replaced by the standard ones.',
      confirmLabel: 'Reset', danger: true,
    });
    if (ok) await run(() => resetStageCriteria(criteria.stage), `${name} criteria reset`);
  }

  return (
    <div className="mt-3 flex flex-col gap-2 pl-4">
      <label htmlFor={`crit-${criteria.stage}`} className={label}>Summary</label>
      <textarea id={`crit-${criteria.stage}`} value={summary} onChange={e => setSummary(e.target.value)} rows={2} maxLength={2000} className={`${input} resize-y`} />
      <span className={label}>Checklist</span>
      {items.map((item, i) => (
        <div key={i} className="flex gap-2">
          <input aria-label={`Checklist item ${i + 1}`} value={item} className={input}
            onChange={e => setItems(items.map((x, j) => (j === i ? e.target.value : x)))} />
          <button type="button" aria-label={`Remove item ${i + 1}`} onClick={() => setItems(items.filter((_, j) => j !== i))} className={btnSecondary}>×</button>
        </div>
      ))}
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" disabled={items.length >= MAX_ITEMS} onClick={() => setItems([...items, ''])} className={btnLink}>Add item</button>
        {!criteria.is_default && <button type="button" disabled={busy} onClick={() => void reset()} className={btnLink}>Reset to standard</button>}
        <button type="button" disabled={busy || !valid} className={`${btnPrimary} ml-auto`}
          onClick={() => void run(() => saveStageCriteria(criteria.stage, { summary: summary.trim(), checklist: trimmed }), `${name} criteria saved`)}>
          Save
        </button>
      </div>
    </div>
  );
}
