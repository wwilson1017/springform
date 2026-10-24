/**
 * A deal's page (`/crm/deals/:id`): its fields, the stage controls (move, Mark won with the
 * closing day, Mark lost with a reason, archive with a reason, restore, merge another deal in),
 * the CRM activity log, stage history, health and touch evidence, and core's timeline and
 * files for `crm.deal`. An archived deal is read-only until restored (the server refuses its
 * stage with 409).
 */
import { useState } from 'react';
import { Link, useParams } from 'react-router';
import { ApiError } from '../../../core/api/client';
import { useJson } from '../../../core/api/useJson';
import { ContactPicker } from '../../../core/contacts/ContactPicker';
import { Attachments } from '../../../core/records/Attachments';
import { Timeline } from '../../../core/records/Timeline';
import { formatDate } from '../../../shared/formatDate';
import { LoadError } from '../../../shared/LoadError';
import { toast } from '../../../shared/toast';
import {
  archiveDeal, dealUrl, markLost, markWon, mergeDeal, restoreDeal, searchDeals, updateDeal,
  type Deal, type DealDetail, type DealHealth, type DealPatch, type Stage, DEAL_ENTITY,
} from '../api';
import { closedOnEditError, ymd } from '../closedOn';
import { OPEN_STAGES, STAGE_COLORS, stageLabel } from '../constants';
import { ActivityLog } from '../components/ActivityLog';
import { ClosedOnDialog } from '../components/ClosedOnDialog';
import { Dialog } from '../components/Dialog';
import { OwnerSelect } from '../components/OwnerSelect';
import { ReasonDialog } from '../components/ReasonDialog';
import { ScorePill, StageBadge, TouchCountPill } from '../components/badges';
import { TouchEvidence } from '../components/TouchEvidence';
import { buildPatch, toForm, type Form } from '../dealPatch';
import { DEAL_TEMPERATURES, temperatureLabel } from '../dealTemperature';
import { formatCents } from '../money';
import { useUsers } from '../useUsers';
import { btn, btnDanger, btnPrimary, btnSecondary, card, field, input, label, muted, sectionTitle } from '../ui';

export function DealDetailPage() {
  const { id } = useParams();
  const { data: deal, error, reload, setData } = useJson<DealDetail>(dealUrl(id!));
  if (error instanceof ApiError && error.status === 404) {
    return <Shell><p className="text-sf-ink-mute">This deal doesn't exist, or you can't see it.</p></Shell>;
  }
  if (error) return <Shell><LoadError label="Couldn't load the deal" onRetry={reload} /></Shell>;
  if (!deal) return <Shell><p className={muted}>Loading…</p></Shell>;
  // A write answers the plain Deal; keep the detail's lists until the reload brings fresh ones.
  const applied = (saved: Deal) => { setData({ ...deal, ...saved }); reload(); };
  return <Shell><DealDetailBody deal={deal} onSaved={applied} reload={reload} /></Shell>;
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-6xl px-4 py-6 md:px-8">
      <Link to="/crm/deals" className="text-sm text-sf-accent-text">← Pipeline</Link>
      <div className="mt-3">{children}</div>
    </div>
  );
}

type Dialogs = 'won' | 'lost' | 'archive' | 'merge' | null;

export function DealDetailBody({ deal, onSaved, reload }: { deal: DealDetail; onSaved: (d: Deal) => void; reload: () => void }) {
  const [dialog, setDialog] = useState<Dialogs>(null);
  const [busy, setBusy] = useState(false);
  const archived = Boolean(deal.archived_at);

  async function run(write: () => Promise<Deal>, done?: string) {
    setDialog(null);
    setBusy(true);
    try {
      onSaved(await write());
      if (done) toast.success(done);
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.detail : "Couldn't save the deal. Reload to see what saved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="m-0 font-display text-2xl font-medium text-sf-ink">{deal.title}</h1>
          <StageBadge stage={deal.stage} />
          <ScorePill score={deal.lead_score} />
          <TouchCountPill count={deal.ai_touch_count} />
        </div>
        <p className="m-0 text-sm text-sf-ink-mute">
          <span className="font-medium text-sf-ink">{formatCents(deal.value_cents, deal.currency)}</span>
          {deal.person_id && <> · <Link to={`/people/${deal.person_id}`} className="text-sf-accent-text">{deal.person_name}</Link></>}
          {deal.organization_id && <> · <Link to={`/organizations/${deal.organization_id}`} className="text-sf-accent-text">{deal.organization_name}</Link></>}
          {deal.stage === 'won' && deal.closed_on && <> · won {deal.closed_on}</>}
        </p>
        {archived && (
          <div role="status" className="flex flex-wrap items-center gap-3 rounded-md border border-sf-line-strong bg-sf-raised px-4 py-3 text-sm text-sf-ink-mute">
            <span className="flex-1">Archived {formatDate(deal.archived_at!)}{deal.archived_reason ? `: ${deal.archived_reason}` : ''}. It is off the board and out of every total.</span>
            <button type="button" disabled={busy} onClick={() => void run(() => restoreDeal(deal.id), 'Deal restored')} className={btnPrimary}>Restore</button>
          </div>
        )}
        {deal.stage === 'lost' && deal.lost_reason && <p className="m-0 text-sm text-sf-ink-mute">Lost because: {deal.lost_reason}</p>}
        {!archived && (
          <StageControls deal={deal} busy={busy}
            onStage={stage => void run(() => updateDeal(deal.id, { stage }))}
            onWon={() => setDialog('won')} onLost={() => setDialog('lost')}
            onArchive={() => setDialog('archive')} onMerge={() => setDialog('merge')} />
        )}
      </header>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-w-0 flex-col gap-6">
          <section className={`${card} p-4`}>
            <h2 className={sectionTitle}>Details</h2>
            {/* key: a fresh form whenever the saved deal changes */}
            <DealFields key={deal.updated_at} deal={deal} readOnly={archived} onSave={patch => run(() => updateDeal(deal.id, patch), 'Saved')} />
          </section>
          <section className={`${card} p-4`}>
            <h2 className={sectionTitle}>Activity</h2>
            <ActivityLog dealId={deal.id} personId={deal.person_id} activities={deal.activity} onChanged={reload} />
          </section>
          <section className={`${card} p-4`}>
            <h2 className={sectionTitle}>Timeline</h2>
            {/* Remounts after a save, so the server's field-change entry shows up. */}
            <Timeline key={deal.updated_at} entityType={DEAL_ENTITY} entityId={deal.id} />
          </section>
        </div>
        <aside className="flex min-w-0 flex-col gap-6">
          <section className={`${card} p-4`}>
            <h2 className={sectionTitle}>Health</h2>
            <Health key={deal.updated_at} dealId={deal.id} />
          </section>
          <section className={`${card} p-4`}>
            <h2 className={sectionTitle}>Stage history</h2>
            {deal.stage_events.length === 0 ? <p className={muted}>No stage changes yet.</p> : (
              <ol className="m-0 flex list-none flex-col gap-2 p-0 text-sm">
                {[...deal.stage_events].reverse().map(e => (
                  <li key={e.id}>
                    <span className="text-sf-ink">{e.old_stage ? `${stageLabel(e.old_stage)} → ${stageLabel(e.new_stage)}` : `Created in ${stageLabel(e.new_stage)}`}</span>
                    <span className="block text-xs text-sf-ink-dim">{e.user_name ?? 'Someone'} · {formatDate(e.changed_at)}</span>
                  </li>
                ))}
              </ol>
            )}
          </section>
          <section className={`${card} p-4`}>
            <h2 className={sectionTitle}>Touches</h2>
            <TouchEvidence key={deal.updated_at} dealId={deal.id} />
          </section>
          <section className={`${card} p-4`}>
            <h2 className={sectionTitle}>Files</h2>
            <Attachments entityType={DEAL_ENTITY} entityId={deal.id} />
          </section>
        </aside>
      </div>

      {dialog === 'won' && <ClosedOnDialog dealTitle={deal.title} onCancel={() => setDialog(null)}
        onConfirm={day => void run(() => markWon(deal.id, day), 'Marked won')} />}
      {dialog === 'lost' && <ReasonDialog variant="lost" dealTitle={deal.title} onCancel={() => setDialog(null)}
        onConfirm={reason => void run(() => markLost(deal.id, reason), 'Marked lost')} />}
      {dialog === 'archive' && <ReasonDialog variant="archive" dealTitle={deal.title} onCancel={() => setDialog(null)}
        onConfirm={reason => void run(() => archiveDeal(deal.id, reason), 'Deal archived')} />}
      {dialog === 'merge' && <MergeDialog deal={deal} onCancel={() => setDialog(null)}
        onConfirm={source => void run(() => mergeDeal(deal.id, source.id), `Merged ${source.title} into this deal`)} />}
    </div>
  );
}

/** The open stages as a stepper, then the two ways to close and the housekeeping actions. */
export function StageControls({ deal, busy, onStage, onWon, onLost, onArchive, onMerge }: {
  deal: Deal;
  busy: boolean;
  onStage: (stage: Stage) => void;
  onWon: () => void;
  onLost: () => void;
  onArchive: () => void;
  onMerge: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div role="group" aria-label="Stage" className="flex flex-wrap gap-1">
        {OPEN_STAGES.map(s => {
          const current = deal.stage === s;
          return (
            <button key={s} type="button" disabled={busy || current} aria-pressed={current} onClick={() => onStage(s)}
              className={`${btn} border ${current ? 'font-medium' : 'border-sf-line-strong bg-transparent text-sf-ink-mute hover:bg-sf-hover'}`}
              style={current ? { background: STAGE_COLORS[s].bg, color: STAGE_COLORS[s].text, borderColor: STAGE_COLORS[s].fill, opacity: 1 } : undefined}>
              {stageLabel(s)}
            </button>
          );
        })}
      </div>
      <span className="mx-1 hidden h-6 w-px bg-sf-line md:block" />
      {deal.stage !== 'won' && <button type="button" disabled={busy} onClick={onWon} className={btnPrimary}>Mark won</button>}
      {deal.stage !== 'lost' && <button type="button" disabled={busy} onClick={onLost} className={btnDanger}>Mark lost</button>}
      <button type="button" disabled={busy} onClick={onMerge} className={btnSecondary}>Merge…</button>
      <button type="button" disabled={busy} onClick={onArchive} className={btnSecondary}>Archive</button>
    </div>
  );
}

function DealFields({ deal, readOnly, onSave }: { deal: Deal; readOnly: boolean; onSave: (patch: DealPatch) => Promise<void> }) {
  const users = useUsers();
  const [base] = useState(() => toForm(deal));
  const [f, setF] = useState(base);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF(x => ({ ...x, [k]: v }));
  const closedError = closedOnEditError({ stage: deal.stage, closed_on: f.closed_on }, base, ymd(new Date()));
  const patch = buildPatch(f, base);
  const error = typeof patch === 'string' ? patch : closedError;
  const dirty = typeof patch === 'string' || Object.keys(patch).length > 0;

  return (
    <form onSubmit={e => { e.preventDefault(); if (!error && typeof patch !== 'string') void onSave(patch); }}>
      <fieldset disabled={readOnly} className="m-0 grid gap-3 border-0 p-0 md:grid-cols-2">
        <div className="md:col-span-2">
          <label htmlFor="f-title" className={label}>Title</label>
          <input id="f-title" value={f.title} maxLength={200} onChange={e => set('title', e.target.value)} className={input} />
        </div>
        <div>
          <label htmlFor="f-value" className={label}>Value</label>
          <div className="flex gap-2">
            <input id="f-value" inputMode="decimal" value={f.value} onChange={e => set('value', e.target.value)} placeholder="0" className={input} />
            <label htmlFor="f-currency" className="sr-only">Currency</label>
            <input id="f-currency" value={f.currency} maxLength={3} onChange={e => set('currency', e.target.value)} className={`${field} w-20 uppercase`} />
          </div>
        </div>
        <div>
          <label htmlFor="f-probability" className={label}>Probability (%)</label>
          <input id="f-probability" type="number" min={0} max={100} value={f.probability} onChange={e => set('probability', e.target.value)} className={input} />
        </div>
        <div>
          <label htmlFor="f-expected" className={label}>Expected close</label>
          <input id="f-expected" type="date" value={f.expected_close} onChange={e => set('expected_close', e.target.value)} className={input} />
        </div>
        {deal.stage === 'won' ? (
          <div>
            <label htmlFor="f-closed" className={label}>Closed on</label>
            <input id="f-closed" type="date" value={f.closed_on} max={ymd(new Date())} onChange={e => set('closed_on', e.target.value)} className={input} />
          </div>
        ) : (
          <div>
            <label htmlFor="f-temp" className={label}>Temperature</label>
            <select id="f-temp" value={f.temperature} onChange={e => set('temperature', e.target.value)} className={input}>
              <option value="">Not set</option>
              {[...DEAL_TEMPERATURES].reverse().map(t => <option key={t} value={t}>{temperatureLabel(t)}</option>)}
            </select>
          </div>
        )}
        <div>
          <span className={label}>Person</span>
          <ContactPicker kind="person" value={f.person} onChange={v => set('person', v)} allowCreate placeholder="Link a person" />
        </div>
        <div>
          <span className={label}>Organization</span>
          <ContactPicker kind="organization" value={f.organization} onChange={v => set('organization', v)} allowCreate placeholder="Link an organization" />
        </div>
        <div>
          <label htmlFor="f-owner" className={label}>Owner</label>
          <OwnerSelect id="f-owner" value={f.owner} onChange={v => set('owner', v)} users={users} currentName={deal.owner_name} />
        </div>
        <div className="md:col-span-2">
          <label htmlFor="f-notes" className={label}>Notes</label>
          <textarea id="f-notes" value={f.notes} rows={3} onChange={e => set('notes', e.target.value)} className={`${input} resize-y`} />
        </div>
      </fieldset>
      {!readOnly && (
        <div className="mt-3 flex flex-wrap items-center justify-end gap-3">
          {dirty && error && <p role="alert" className="m-0 mr-auto text-sm text-sf-red-text">{error}</p>}
          {dirty && <button type="button" onClick={() => setF(base)} className={btnSecondary}>Discard</button>}
          <button type="submit" disabled={!dirty || Boolean(error)} className={btnPrimary}>Save</button>
        </div>
      )}
    </form>
  );
}

function Health({ dealId }: { dealId: number }) {
  const { data, error, reload } = useJson<DealHealth>(`${dealUrl(dealId)}/health`);
  if (error) return <LoadError label="Couldn't load the deal's health" onRetry={reload} compact />;
  if (!data) return <p className={muted}>Loading…</p>;
  const factors = Object.entries(data.factors);
  if (data.score == null && factors.length === 0 && data.flags.length === 0) {
    return <p className={muted}>No health score yet. It appears once the deal has some history.</p>;
  }
  return (
    <div className="flex flex-col gap-2 text-sm">
      {data.score != null && <p className="m-0 text-sf-ink">Score <span className="font-display text-xl">{data.score}</span></p>}
      {data.flags.length > 0 && (
        <ul className="m-0 flex list-none flex-wrap gap-1 p-0">
          {data.flags.map(f => <li key={f} className="rounded bg-sf-raised px-1.5 py-0.5 text-xs text-sf-ink-mute">{f.replace(/_/g, ' ')}</li>)}
        </ul>
      )}
      {factors.length > 0 && (
        <dl className="m-0 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-xs">
          {factors.map(([k, v]) => (
            <div key={k} className="contents"><dt className="text-sf-ink-mute">{k.replace(/_/g, ' ')}</dt><dd className="m-0 text-right text-sf-ink">{Math.round(v * 100) / 100}</dd></div>
          ))}
        </dl>
      )}
    </div>
  );
}

/** Fold another deal into this one: its timeline, files and activity move here and it is archived. */
function MergeDialog({ deal, onCancel, onConfirm }: { deal: Deal; onCancel: () => void; onConfirm: (source: Deal) => void }) {
  const [q, setQ] = useState('');
  const [hits, setHits] = useState<Deal[] | null>(null);
  const [source, setSource] = useState<Deal | null>(null);

  async function search(e: React.FormEvent) {
    e.preventDefault();
    try {
      setHits((await searchDeals(q.trim())).filter(d => d.id !== deal.id));
    } catch {
      toast.error("Couldn't search deals.");
    }
  }

  return (
    <Dialog title="Merge a deal into this one" subtitle={`The other deal's notes, files and activity move to ${deal.title}, and it is archived.`} onClose={onCancel}>
      <form onSubmit={search} className="flex gap-2">
        <label htmlFor="merge-q" className="sr-only">Find the other deal</label>
        <input id="merge-q" value={q} onChange={e => setQ(e.target.value)} placeholder="Find the other deal" className={input} />
        <button type="submit" disabled={!q.trim()} className={btnSecondary}>Search</button>
      </form>
      {hits && (hits.length === 0 ? <p className={`${muted} mt-3`}>No other deal matches.</p> : (
        <ul className="m-0 mt-3 max-h-60 list-none overflow-y-auto p-0">
          {hits.map(h => (
            <li key={h.id}>
              <label className="flex cursor-pointer items-center gap-2 py-1.5 text-sm text-sf-ink">
                <input type="radio" name="merge-source" checked={source?.id === h.id} onChange={() => setSource(h)} className="accent-sf-accent" />
                <span className="min-w-0 flex-1 truncate">{h.title}</span>
                <span className="text-xs text-sf-ink-dim">{stageLabel(h.stage)} · {formatCents(h.value_cents, h.currency)}</span>
              </label>
            </li>
          ))}
        </ul>
      ))}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onCancel} className={btnSecondary}>Cancel</button>
        <button type="button" disabled={!source} onClick={() => source && onConfirm(source)} className={btnPrimary}>Merge</button>
      </div>
    </Dialog>
  );
}
