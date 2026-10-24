/**
 * The Today list's pure rules: which rows show collapsed, what each row says, when to refetch.
 */
import type { TodayItem } from './api';
import { formatCents } from './money';

/** Ranked rows shown before "Show all". */
export const TODAY_COLLAPSED = 5;

/** The core reminder row a Today item carries (`TodayItem.reminder`). */
export interface TodayReminder {
  id: number;
  title: string;
  note?: string;
  due_at: string;
  status?: string;
  fired_at?: string | null;
  entity_type?: string | null;
  entity_id?: number | null;
}

export interface TodayCollapse {
  visible: TodayItem[];
  hiddenCount: number;
}

/** Collapsed: the first ranked rows. Expanded: everything, unranked rows included. */
export function collapseToday(items: TodayItem[], expanded: boolean): TodayCollapse {
  const ranked = items.filter(i => i.rank !== null).slice(0, TODAY_COLLAPSED);
  return { visible: expanded ? items : ranked, hiddenCount: items.length - ranked.length };
}

/** "idle 12d · $4,800" for a deal row. */
export function dealEvidence(lastActivityAt: string | null, valueCents: number, currency: string, now = Date.now()): string {
  const money = formatCents(valueCents, currency);
  if (!lastActivityAt) return `no contact logged · ${money}`;
  const days = Math.max(0, Math.floor((now - Date.parse(lastActivityAt)) / 86_400_000));
  return `idle ${days}d · ${money}`;
}

/** Where a reminder row links: its deal when it has one, else the core Reminders page. */
export function reminderHref(r: TodayReminder): string {
  return r.entity_type === 'crm.deal' && r.entity_id ? `/crm/deals/${r.entity_id}` : '/reminders';
}

/** Milliseconds until the list should refetch: the server's `next_refresh_at` (local midnight),
 *  clamped to [30 s, 25 h] so a bad value can neither spin nor stall. */
export function msUntilRefresh(nextRefreshAt: string, now: number): number {
  const target = Date.parse(nextRefreshAt);
  if (!Number.isFinite(target)) return 60 * 60 * 1000;
  return Math.min(Math.max(target - now, 30 * 1000), 25 * 60 * 60 * 1000);
}
