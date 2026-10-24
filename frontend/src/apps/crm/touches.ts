/**
 * Weekly Touches routing: a rep's detail lives at `touches/<owner>` where owner is a user id or
 * `unassigned`, carrying an applied custom window as `?start&end`.
 */
import type { TouchWindow } from './api';

export const UNASSIGNED_OWNER = 'unassigned';

export function ownerParamOf(userId: number | null): string {
  return userId === null ? UNASSIGNED_OWNER : String(userId);
}

const MAX_OWNER_ID = 2147483647;

/** A URL segment the API will accept as `owner`, or null (a hand-edited URL). */
export function parseOwnerParam(raw: string | undefined): string | null {
  if (raw === UNASSIGNED_OWNER) return raw;
  if (raw === undefined || !/^[0-9]{1,10}$/.test(raw)) return null;
  const id = Number(raw);
  return id >= 1 && id <= MAX_OWNER_ID ? raw : null;
}

/** The link to a rep's detail, carrying a custom window as the install-local days the API applied
 *  (`start_day`, `end_day`), never days read off its UTC instants. */
export function touchDetailPath(userId: number | null, window: TouchWindow): string {
  const path = `/crm/touches/${ownerParamOf(userId)}`;
  return window.custom ? `${path}?${new URLSearchParams({ start: window.start_day, end: window.end_day })}` : path;
}

/** "Oct 17 – Oct 24, 2026", from the window's install-local days; "Last 7 days · …" when rolling. */
export function windowText(window: TouchWindow): string {
  const day = (ymd: string, year: boolean) => {
    const [y, m, d] = ymd.split('-').map(Number);
    return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: 'short', day: 'numeric', ...(year ? { year: 'numeric' } : {}) });
  };
  const sameYear = window.start_day.slice(0, 4) === window.end_day.slice(0, 4);
  const days = window.start_day === window.end_day ? day(window.end_day, true)
    : `${day(window.start_day, !sameYear)} – ${day(window.end_day, true)}`;
  return window.custom ? days : `${window.label} · ${days}`;
}
