/**
 * The pipeline board's pure rules: which deals show, in which column, in what order, with what
 * totals. Kept out of the page so they test without a DOM.
 */
import type { Deal, Stage } from './api';
import { CLOSED_STAGES, OPEN_STAGES, STAGE_ORDER } from './constants';

export interface StageColumn {
  stage: Stage;
  deals: Deal[];
  count: number;
  totalCents: number;
}

export interface BoardFilters {
  /** A user id, `'unassigned'`, or `''` for everyone. */
  owner: string;
  /** A tier, `'none'` for untriaged, or `''` for any. */
  temperature: string;
  /** Deal ids a server search matched, or null when no search is active. */
  matchIds: ReadonlySet<number> | null;
}

export const NO_FILTERS: BoardFilters = { owner: '', temperature: '', matchIds: null };

export function filterDeals(deals: readonly Deal[], f: BoardFilters): Deal[] {
  return deals.filter(d =>
    (f.owner === '' || (f.owner === 'unassigned' ? d.owner_user_id === null : String(d.owner_user_id) === f.owner)) &&
    (f.temperature === '' || (f.temperature === 'none' ? d.deal_temperature === null : d.deal_temperature === f.temperature)) &&
    (f.matchIds === null || f.matchIds.has(d.id)));
}

/**
 * One column per visible stage, in pipeline order, each holding exactly the cards it shows and
 * the count and total OF those cards (so a filter or an optimistic move keeps them honest).
 * Inside a column the highest lead score leads; ties keep the server's order.
 */
export function groupByStage(deals: readonly Deal[], stages: readonly Stage[] = STAGE_ORDER): StageColumn[] {
  return stages.map(stage => {
    const inStage = deals
      .map((deal, i) => ({ deal, i }))
      .filter(x => x.deal.stage === stage)
      .sort((a, b) => (b.deal.lead_score ?? -1) - (a.deal.lead_score ?? -1) || a.i - b.i)
      .map(x => x.deal);
    return { stage, deals: inStage, count: inStage.length, totalCents: inStage.reduce((s, d) => s + d.value_cents, 0) };
  });
}

/** The open pipeline's count and value, over live deals only. */
export function openTotals(deals: readonly Deal[]): { count: number; cents: number } {
  const open = deals.filter(d => OPEN_STAGES.includes(d.stage) && !d.archived_at);
  return { count: open.length, cents: open.reduce((s, d) => s + d.value_cents, 0) };
}

/** The stages a board shows: open ones always, won and lost on request. */
export const visibleStages = (showClosed: boolean): Stage[] =>
  showClosed ? STAGE_ORDER : STAGE_ORDER.filter(s => !CLOSED_STAGES.includes(s));

/** The deal as it reads after a move to `stage`, for the optimistic board (the server's
 *  `classify` rules: a closed stage sets probability, leaving won clears closed_on, leaving
 *  lost clears the reason). The server's answer replaces it. */
export function movedDeal(deal: Deal, stage: Stage, today: string): Deal {
  if (stage === deal.stage) return deal;
  const base = { ...deal, stage, lost_reason: deal.stage === 'lost' ? '' : deal.lost_reason };
  if (stage === 'won') return { ...base, status: 'won', probability: 100, closed_on: today };
  if (stage === 'lost') return { ...base, status: 'lost', probability: 0, closed_on: null };
  return { ...base, status: 'open', closed_on: null };
}

/** "Last contact 3d ago", from the newest activity or note on the deal. */
export function lastContactLabel(lastActivityAt: string | null, now: Date = new Date()): string {
  if (!lastActivityAt) return 'No contact logged';
  const days = Math.floor((now.getTime() - Date.parse(lastActivityAt)) / 86_400_000);
  if (!Number.isFinite(days)) return 'No contact logged';
  return days <= 0 ? 'Last contact today' : `Last contact ${days}d ago`;
}

const SHOW_CLOSED_KEY = 'crm.pipeline.showClosed';

export function loadShowClosed(): boolean {
  try { return localStorage.getItem(SHOW_CLOSED_KEY) === '1'; } catch { return false; }
}

export function saveShowClosed(show: boolean): void {
  // A convenience, never a correctness input: private mode just forgets it.
  try { localStorage.setItem(SHOW_CLOSED_KEY, show ? '1' : '0'); } catch { /* not remembered */ }
}
