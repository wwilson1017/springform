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

/** The link to a rep's detail, keeping an applied custom range (`YYYY-MM-DD` days, as the API
 *  takes them; the response's window is UTC instants, which the API would refuse back). */
export function touchDetailPath(userId: number | null, applied: { start: string; end: string } | null): string {
  const path = `/crm/touches/${ownerParamOf(userId)}`;
  return applied ? `${path}?${new URLSearchParams({ start: applied.start, end: applied.end })}` : path;
}
