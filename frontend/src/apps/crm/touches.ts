/**
 * Weekly Touches routing: a rep's detail lives at `touches/<owner>` where owner is a user id or
 * `unassigned`, carrying an applied custom window as `?start&end`.
 */

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

/** The app-relative link to a rep's detail, keeping a custom window. */
export function touchDetailPath(userId: number | null, window: { start: string; end: string; custom: boolean }): string {
  const path = `/crm/touches/${ownerParamOf(userId)}`;
  return window.custom ? `${path}?${new URLSearchParams({ start: window.start, end: window.end })}` : path;
}
