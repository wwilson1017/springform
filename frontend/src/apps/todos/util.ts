// Todo GTD — pure helpers (unit-tested in util.test.ts).

import { parseUTC } from './lib/date';
import type { Member } from './types';

/** YYYY-MM-DD "today" in the LIST's time zone (`tz`, from the filters payload) —
 * the same date the server and AI tools use, whatever zone this browser is in.
 * Without `tz` (the payload has not landed yet, or an unknown zone name) it is
 * the browser's local date. Never UTC: due dates carry local calendar intent. */
export function todayStr(now: Date = new Date(), tz?: string): string {
  if (tz) {
    try {
      // Assembled from parts: a locale string is not a serialization contract.
      const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
      }).formatToParts(now);
      const get = (type: string) => parts.find(p => p.type === type)?.value ?? '';
      return `${get('year')}-${get('month')}-${get('day')}`;
    } catch {
      // unknown zone name — fall through to the browser's date
    }
  }
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/** A Date whose LOCAL calendar fields are the list's today (at noon, clear of any
 * DST edge) — for date math written against local getters, like the quick-add parser. */
export function zonedNow(tz?: string, now: Date = new Date()): Date {
  const [y, m, d] = todayStr(now, tz).split('-').map(Number);
  return new Date(y, m - 1, d, 12);
}

/** Area picker options: a row's own area always has one, even once archived (the pickers
 * only list active areas). */
export function withOwnArea(
  areas: { id: number; name: string }[], id?: number | null, name?: string | null,
): { id: number; name: string }[] {
  return id && !areas.some(a => a.id === id) ? [{ id, name: name ?? 'Archived area' }, ...areas] : areas;
}

export function parseTags(input: string): string[] {
  return input.split(',').map(t => t.trim()).filter(Boolean);
}

/** Free-text filter behind the per-tab search boxes: a substring match across title, notes,
 * context, project name, tags, and people.
 *
 * Context matching is `contextFacet.ts`'s `matchesContexts` (the facet is multi-select). */
export function matchesFilter(
  todo: {
    title: string; notes: string; context: string;
    project_name: string | null; tags: string[]; people?: string[];
  },
  search: string,
): boolean {
  const q = search.trim().toLowerCase();
  if (!q) return true;
  return [todo.title, todo.notes, todo.context, todo.project_name || '', ...todo.tags,
    ...(todo.people ?? [])]
    .some(field => field.toLowerCase().includes(q));
}

/** "3d" / "5w" age chip for Waiting items — how long something has sat. */
export function formatAge(isoTimestamp: string, now: Date = new Date()): string {
  const then = parseUTC(isoTimestamp);
  const days = Math.max(0, Math.floor((now.getTime() - then.getTime()) / 86_400_000));
  if (days < 1) return 'today';
  if (days < 7) return `${days}d`;
  if (days < 60) return `${Math.floor(days / 7)}w`;
  return `${Math.floor(days / 30)}mo`;
}

/** Days a todo has gone untouched (for the Review page's stale list).
 *
 * Parses through `parseUTC` rather than `new Date()`: ECMAScript guarantees parsing for exactly
 * three fraction digits and an explicit zone, and `vite.config.ts` targets `safari16`. An
 * Invalid Date here does not merely mis-render: `NaN >= STALE_DAYS` is `false`, so a genuinely
 * stale todo would be silently dropped from the Review page's list rather than shown. */
export function daysSince(isoTimestamp: string, now: Date = new Date()): number {
  return Math.floor((now.getTime() - parseUTC(isoTimestamp).getTime()) / 86_400_000);
}

/** Human label for a due date: Today / Tomorrow / Mon Aug 10 / overdue flag. */
export function dueLabel(due: string, today: string): { text: string; overdue: boolean } {
  if (due === today) return { text: 'Today', overdue: false };
  const [y, m, d] = due.split('-').map(Number);
  // Build from parts — new Date('YYYY-MM-DD') parses as UTC midnight and
  // renders the previous day west of Greenwich.
  const date = new Date(y, m - 1, d);
  const [ty, tm, td] = today.split('-').map(Number);
  // td + 1, not +24h: the day the clocks change is 23 or 25 hours long.
  const tomorrow = new Date(ty, tm - 1, td + 1);
  if (date.getTime() === tomorrow.getTime()) return { text: 'Tomorrow', overdue: false };
  const text = date.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  return { text, overdue: due < today };
}

/** A member's name from the filters' `members`; a deactivated one reads as "a former member". */
export function memberName(members: Member[] | undefined, id: number | null | undefined): string | null {
  if (id === null || id === undefined) return null;
  return members?.find(m => m.id === id)?.name ?? 'a former member';
}
