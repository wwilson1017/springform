/**
 * The pipeline board: one column per stage, a card per deal. A deal moves by dragging its card
 * to another column or with the card's "Move to" menu (keyboard and touch); several move at
 * once with the checkboxes and the bulk bar. Moving into Won asks the closing day, into Lost
 * the reason. Filters (owner, temperature), a server search, a won/lost toggle and an archived
 * toggle narrow what shows; every column's count and total are of the cards it shows.
 *
 * Moves are optimistic: the card moves at once and the server's answer replaces it. A refusal
 * (4xx: nothing written) puts it back; an unknown outcome (5xx, dropped connection) reloads
 * the board instead of guessing.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { ApiError, fetchJson } from '../../../core/api/client';
import { useJson } from '../../../core/api/useJson';
import { useAuth } from '../../../core/auth/AuthContext';
import { LoadError } from '../../../shared/LoadError';
import { toast } from '../../../shared/toast';
import {
  boardUrl, bulkMove, markLost, markWon, searchUrl, stageCriteriaUrl, updateDeal,
  type Board, type Deal, type Stage, type StageCriteria,
} from '../api';
import { classifyBulkMove, describeBulkMove } from '../bulkOutcome';
import { ymd } from '../closedOn';
import { CLOSED_STAGES, STAGE_COLORS, STAGE_ORDER, stageLabel } from '../constants';
import { ClosedOnDialog } from '../components/ClosedOnDialog';
import { DealForm } from '../components/DealForm';
import { DealTemperatureIcon } from '../components/DealTemperatureIcon';
import { ReasonDialog } from '../components/ReasonDialog';
import { ScorePill, TouchCountPill } from '../components/badges';

import { formatCents } from '../money';
import {
  NO_FILTERS, filterDeals, groupByStage, lastContactLabel, loadShowClosed, movedDeal, openTotals,
  saveShowClosed, visibleStages, type BoardFilters,
} from '../pipelineBoard';
import { btnLink, btnPrimary, btnSecondary, field, muted, pageTitle } from '../ui';
import { useUsers } from '../useUsers';

/** A move that needs an answer first: the closing day for Won, the reason for Lost. */
type PendingMove = { ids: number[]; stage: 'won' | 'lost'; title: string };

export function PipelinePage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const focusStage = params.get('stage');
  const { user } = useAuth();
  const users = useUsers();
  const [includeArchived, setIncludeArchived] = useState(false);
  const [showClosed, setShowClosed] = useState(() => loadShowClosed() || CLOSED_STAGES.includes(focusStage as Stage));
  const [filters, setFilters] = useState<BoardFilters>(NO_FILTERS);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [pending, setPending] = useState<PendingMove | null>(null);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const criteria = useJson<StageCriteria[]>(stageCriteriaUrl).data;

  // The board, with functional updates for optimistic moves; a response for a stale URL is dropped.
  const url = boardUrl(includeArchived);
  const [board, setBoard] = useState<{ url: string; data: Board } | null>(null);
  const [loadError, setLoadError] = useState<Error | null>(null);
  const latestUrl = useRef(url);
  const load = useCallback(() => {
    latestUrl.current = url;
    return fetchJson<Board>(url).then(
      data => { if (latestUrl.current === url) { setBoard({ url, data }); setLoadError(null); } return true; },
      (e: Error) => { if (latestUrl.current === url) setLoadError(e); return false; },
    );
  }, [url]);
  useEffect(() => { void load(); }, [load]);
  const data = board?.url === url ? board.data : null;
  const patchDeals = useCallback((fn: (d: Deal) => Deal) =>
    setBoard(b => b && { ...b, data: { ...b.data, deals: b.data.deals.map(fn) } }), []);

  // Server search (every word, prefix, accent-folded). Until it answers, the board stays unfiltered.
  const [match, setMatch] = useState<{ q: string; ids: Set<number> } | null>(null);
  const q = query.trim();
  useEffect(() => {
    if (!q) return;
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      fetchJson<Deal[]>(searchUrl(q, includeArchived), ctrl.signal).then(
        rows => setMatch({ q, ids: new Set(rows.map(r => r.id)) }),
        () => { if (!ctrl.signal.aborted) toast.error("Couldn't search deals."); },
      );
    }, 250);
    return () => { clearTimeout(t); ctrl.abort(); };
  }, [q, includeArchived]);
  const matchIds = q && match?.q === q ? match.ids : null;

  const stages = useMemo(() => visibleStages(showClosed), [showClosed]);
  const shown = useMemo(() => (data ? filterDeals(data.deals, { ...filters, matchIds }) : []), [data, filters, matchIds]);
  const columns = useMemo(() => groupByStage(shown, stages), [shown, stages]);
  const totals = openTotals(data?.deals ?? []);
  const byId = useMemo(() => new Map((data?.deals ?? []).map(d => [d.id, d])), [data]);

  // ?stage= from the dashboard: bring that column into view once the board is on screen.
  const scrolled = useRef(false);
  useEffect(() => {
    if (!data || !focusStage || scrolled.current) return;
    scrolled.current = true;
    document.getElementById(`stage-${focusStage}`)?.scrollIntoView({ block: 'nearest', inline: 'start' });
  }, [data, focusStage]);

  /** One deal to `stage`. Won and Lost go through their dialogs first. */
  function requestMove(deal: Deal, stage: Stage) {
    if (stage === deal.stage) return;
    if (deal.archived_at) return toast.error('Restore this deal before changing its stage.');
    if (stage === 'won' || stage === 'lost') return setPending({ ids: [deal.id], stage, title: deal.title });
    void moveOne(deal, stage, () => updateDeal(deal.id, { stage }));
  }

  async function moveOne(deal: Deal, stage: Stage, write: () => Promise<Deal>) {
    patchDeals(d => (d.id === deal.id ? movedDeal(d, stage, ymd(new Date())) : d));
    try {
      const saved = await write();
      patchDeals(d => (d.id === saved.id ? saved : d));
    } catch (e) {
      if (e instanceof ApiError && e.status < 500) {
        patchDeals(d => (d.id === deal.id ? deal : d));
        toast.error(e.detail || `Couldn't move ${deal.title}.`);
      } else {
        toast.error(`Couldn't confirm the move of ${deal.title}; the board was reloaded.`);
        void load();
      }
    }
  }

  async function moveMany(ids: number[], stage: Stage, closedOn?: string) {
    const before = new Map(ids.flatMap(id => (byId.has(id) ? [[id, byId.get(id)!] as const] : [])));
    const today = ymd(new Date());
    patchDeals(d => (before.has(d.id) && !d.archived_at ? movedDeal(d, stage, closedOn ?? today) : d));
    setBusy(true);
    let outcome;
    try {
      outcome = classifyBulkMove(await bulkMove(ids, stage, closedOn));
    } catch (e) {
      outcome = classifyBulkMove({ thrown: e instanceof ApiError ? { status: e.status, reason: e.detail } : {} });
    }
    if (outcome.kind === 'rejected') patchDeals(d => before.get(d.id) ?? d);
    const reconciled = await load();
    setBusy(false);
    const notice = describeBulkMove(outcome, ids.length, reconciled);
    if (notice) toast.error(notice.text);
    if (outcome.kind === 'clean' || outcome.kind === 'skips') setSelected(new Set());
  }

  function confirmPending(answer: string) {
    const move = pending!;
    setPending(null);
    if (move.ids.length > 1) return void moveMany(move.ids, move.stage, move.stage === 'won' ? answer : undefined);
    const deal = byId.get(move.ids[0]);
    if (!deal) return;
    void moveOne(deal, move.stage, () => (move.stage === 'won' ? markWon(deal.id, answer) : markLost(deal.id, answer)));
  }

  function bulkTo(stage: Stage) {
    const ids = [...selected].filter(id => byId.get(id) && !byId.get(id)!.archived_at);
    if (ids.length === 0) return toast.error('Archived deals cannot be moved; restore them first.');
    // Bulk Lost takes no reason (one reason rarely fits many deals); Won still asks the day.
    if (stage === 'won') return setPending({ ids, stage, title: `${ids.length} deals` });
    void moveMany(ids, stage);
  }

  async function cycleTemperature(deal: Deal, next: Deal['deal_temperature']) {
    try {
      const saved = await updateDeal(deal.id, { deal_temperature: next });
      patchDeals(d => (d.id === saved.id ? saved : d));
    } catch {
      toast.error("Couldn't change the temperature.");
      throw new Error('temperature');
    }
  }

  const toggle = (id: number) => setSelected(s => {
    const next = new Set(s);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  return (
    <div className="flex flex-col">
      <div className="flex flex-wrap items-end gap-3 px-4 pt-6 md:px-8">
        <div className="mr-auto">
          <h1 className={pageTitle}>Pipeline</h1>
          <p className="m-0 mt-1 text-sm text-sf-ink-mute">
            Open pipeline <span className="font-medium text-sf-ink">{formatCents(totals.cents)}</span> across {totals.count} deal{totals.count === 1 ? '' : 's'}
          </p>
        </div>
        <button type="button" onClick={() => setCreating(true)} className={btnPrimary}>New deal</button>
      </div>

      <div className="flex flex-wrap items-center gap-2 px-4 py-4 md:px-8">
        <label htmlFor="deal-search" className="sr-only">Search deals</label>
        <input id="deal-search" type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search deals, people, organizations"
          className={`${field} w-full md:w-72`} />
        <label htmlFor="filter-owner" className="sr-only">Owner</label>
        <select id="filter-owner" value={filters.owner} onChange={e => setFilters(f => ({ ...f, owner: e.target.value }))} className={field}>
          <option value="">Any owner</option>
          {user && <option value={String(user.id)}>Mine</option>}
          {users.filter(u => u.id !== user?.id).map(u => <option key={u.id} value={String(u.id)}>{u.name}</option>)}
          <option value="unassigned">Unassigned</option>
        </select>
        <label htmlFor="filter-temp" className="sr-only">Temperature</label>
        <select id="filter-temp" value={filters.temperature} onChange={e => setFilters(f => ({ ...f, temperature: e.target.value }))} className={field}>
          <option value="">Any temperature</option>
          <option value="hot">Hot</option>
          <option value="warm">Warm</option>
          <option value="cold">Cold</option>
          <option value="none">Not set</option>
        </select>
        <label className="flex items-center gap-1.5 text-sm text-sf-ink-mute">
          <input type="checkbox" checked={showClosed} className="accent-sf-accent"
            onChange={e => { setShowClosed(e.target.checked); saveShowClosed(e.target.checked); }} />
          Won and lost
        </label>
        <label className="flex items-center gap-1.5 text-sm text-sf-ink-mute">
          <input type="checkbox" checked={includeArchived} onChange={e => setIncludeArchived(e.target.checked)} className="accent-sf-accent" />
          Archived
        </label>
      </div>

      {loadError && !data ? <div className="px-4 md:px-8"><LoadError label="Couldn't load the pipeline" onRetry={() => void load()} /></div>
        : !data ? <p className={`${muted} px-4 md:px-8`}>Loading…</p>
        : (
          <>
            {data.deals_truncated && <p className={`${muted} px-4 pb-2 md:px-8`}>Showing the 200 most recently edited deals in each stage. Search to find older ones.</p>}
            {data.deals.length === 0 && (
              <p className={`${muted} px-4 pb-4 md:px-8`}>No deals yet. <button type="button" onClick={() => setCreating(true)} className={btnLink}>Create the first one</button>.</p>
            )}
            <div className="flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-24 md:snap-none md:px-8">
              {columns.map(col => (
                <Column key={col.stage} stage={col.stage} count={col.count} totalCents={col.totalCents}
                  summary={criteria?.find(c => c.stage === col.stage)?.summary}
                  onDropDeal={id => { const d = byId.get(id); if (d) requestMove(d, col.stage); }}>
                  {col.deals.length === 0 ? <p className="m-0 px-1 py-6 text-center text-xs text-sf-ink-dim">No deals</p>
                    : col.deals.map(d => (
                      <DealCard key={d.id} deal={d} selected={selected.has(d.id)} onToggle={() => toggle(d.id)}
                        onMove={stage => requestMove(d, stage)} onCycle={next => cycleTemperature(d, next)}
                        ownerName={d.owner_name} />
                    ))}
                </Column>
              ))}
            </div>
          </>
        )}

      {selected.size > 0 && (
        <div role="region" aria-label="Bulk actions"
          className="fixed inset-x-0 bottom-0 z-40 flex flex-wrap items-center gap-2 border-t border-sf-line-strong bg-sf-card px-4 py-3 shadow-lg md:px-8">
          <span className="text-sm text-sf-ink">{selected.size} selected</span>
          <label htmlFor="bulk-stage" className="sr-only">Move selected to</label>
          <select id="bulk-stage" value="" disabled={busy} onChange={e => e.target.value && bulkTo(e.target.value as Stage)} className={field}>
            <option value="">Move to…</option>
            {STAGE_ORDER.map(s => <option key={s} value={s}>{stageLabel(s)}</option>)}
          </select>
          <button type="button" onClick={() => setSelected(new Set())} className={btnSecondary}>Clear</button>
        </div>
      )}

      {pending?.stage === 'won' && <ClosedOnDialog dealTitle={pending.title} onConfirm={confirmPending} onCancel={() => setPending(null)} />}
      {pending?.stage === 'lost' && <ReasonDialog variant="lost" dealTitle={pending.title} onConfirm={confirmPending} onCancel={() => setPending(null)} />}
      {creating && <DealForm onClose={() => setCreating(false)} onCreated={d => { setCreating(false); navigate(`/crm/deals/${d.id}`); }} />}
    </div>
  );
}

const DRAG_TYPE = 'application/x-crm-deal';

function Column({ stage, count, totalCents, summary, onDropDeal, children }: {
  stage: Stage;
  count: number;
  totalCents: number;
  summary?: string;
  onDropDeal: (id: number) => void;
  children: React.ReactNode;
}) {
  const [over, setOver] = useState(false);
  const accepts = (e: DragEvent) => e.dataTransfer.types.includes(DRAG_TYPE);
  return (
    <section id={`stage-${stage}`} aria-label={`${stageLabel(stage)}: ${count} deals`}
      onDragOver={e => { if (accepts(e)) { e.preventDefault(); setOver(true); } }}
      onDragLeave={() => setOver(false)}
      onDrop={e => { setOver(false); const id = Number(e.dataTransfer.getData(DRAG_TYPE)); if (id) { e.preventDefault(); onDropDeal(id); } }}
      className={`flex w-[85vw] shrink-0 snap-start flex-col rounded-lg border bg-sf-raised/50 md:w-72 ${over ? 'border-sf-accent' : 'border-sf-line'}`}>
      <header className="flex items-center gap-2 border-b border-sf-line px-3 py-2.5" title={summary}>
        <span aria-hidden className="h-2.5 w-2.5 rounded-full" style={{ background: STAGE_COLORS[stage].fill }} />
        <h2 className="m-0 text-sm font-medium" style={{ color: STAGE_COLORS[stage].text }}>{stageLabel(stage)}</h2>
        <span className="text-xs text-sf-ink-dim">{count}</span>
        <span className="ml-auto text-xs font-medium text-sf-ink-mute">{formatCents(totalCents)}</span>
      </header>
      <div className="flex flex-col gap-2 p-2">{children}</div>
    </section>
  );
}

function DealCard({ deal, selected, onToggle, onMove, onCycle, ownerName }: {
  deal: Deal;
  selected: boolean;
  onToggle: () => void;
  onMove: (stage: Stage) => void;
  onCycle: (next: Deal['deal_temperature']) => Promise<unknown>;
  ownerName: string | null;
}) {
  const archived = Boolean(deal.archived_at);
  const c = STAGE_COLORS[deal.stage];
  const who = [deal.organization_name, deal.person_name].filter(Boolean).join(' · ');
  return (
    <article draggable={!archived}
      onDragStart={e => { e.dataTransfer.setData(DRAG_TYPE, String(deal.id)); e.dataTransfer.effectAllowed = 'move'; }}
      aria-label={deal.title}
      className={`rounded-md border border-sf-line bg-sf-card p-3 text-sm shadow-sm ${archived ? 'opacity-60' : 'cursor-grab'}`}
      style={{ borderLeft: `3px solid ${c.fill}` }}>
      <div className="flex items-start gap-2">
        <input type="checkbox" checked={selected} onChange={onToggle} aria-label={`Select ${deal.title}`} className="mt-0.5 accent-sf-accent" />
        <Link to={`/crm/deals/${deal.id}`} className="min-w-0 flex-1 font-medium text-sf-ink no-underline hover:underline">{deal.title}</Link>
        <DealTemperatureIcon value={deal.deal_temperature} onCycle={onCycle} disabled={archived} />
      </div>
      {who && <div className="mt-1 truncate text-xs text-sf-ink-mute">{who}</div>}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className="font-medium text-sf-ink">{formatCents(deal.value_cents, deal.currency)}</span>
        <ScorePill score={deal.lead_score} compact />
        <TouchCountPill count={deal.ai_touch_count} />
        {archived ? <span className="ml-auto rounded bg-sf-raised px-1.5 py-0.5 text-xs text-sf-ink-mute">Archived</span> : (
          <>
            <label htmlFor={`move-${deal.id}`} className="sr-only">Move {deal.title} to</label>
            <select id={`move-${deal.id}`} value="" onChange={e => e.target.value && onMove(e.target.value as Stage)}
              className="ml-auto cursor-pointer rounded border border-sf-line bg-sf-card px-1 py-0.5 text-xs text-sf-ink-mute">
              <option value="">Move…</option>
              {STAGE_ORDER.filter(s => s !== deal.stage).map(s => <option key={s} value={s}>{stageLabel(s)}</option>)}
            </select>
          </>
        )}
      </div>
      <div className="mt-1.5 truncate text-xs text-sf-ink-dim">{ownerName ?? 'Unassigned'} · {lastContactLabel(deal.last_activity_at)}</div>
    </article>
  );
}
