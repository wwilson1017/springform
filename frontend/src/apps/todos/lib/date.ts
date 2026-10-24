// Server-timestamp helpers (the subset of cake-os core/utils/date.ts this app uses).

const HAS_TZ = /(?:Z|[+-]\d{2}:?\d{2})$/i;
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
const ISO_START = /^\d{4}-\d{2}-\d{2}/;

/**
 * Rewrite a server timestamp into the ONE date-time shape ECMAScript guarantees every engine can
 * parse: `YYYY-MM-DDTHH:mm:ss.sssZ` or `…±HH:MM`. Exported so it can be tested as a string:
 * vitest runs on V8, which accepts the un-normalized shapes natively, so only a string
 * assertion guards the Safari cases.
 */
export function normalizeTimestamp(raw: string): string {
  let s = raw
    .trim()
    // Date/time separator. First whitespace run only.
    .replace(/\s+/, 'T')
    // The spec guarantees exactly three fraction digits.
    .replace(/\.(\d+)/, (_m, digits: string) => '.' + digits.slice(0, 3).padEnd(3, '0'));

  // Zone normalization applies only once a time component exists. Without that guard the trailing
  // `-30` of a date reads as an offset and the value is destroyed.
  if (/T\d{2}:\d{2}/.test(s)) {
    s = s
      .replace(/\s+(?=(?:[Zz]|[+-]\d{2}(?::?\d{2})?)$)/, '') // `12:00:00 +0000` → `12:00:00+0000`
      .replace(/z$/, 'Z') // lowercase `z` is legal ISO-8601, not legal ECMAScript
      .replace(/([+-]\d{2})(\d{2})$/, '$1:$2') // `±HHMM` → `±HH:MM`
      .replace(/([+-]\d{2})$/, '$1:00'); // `±HH` → `±HH:00`
  }

  // A date-only value gets an explicit midnight: `2026-07-30Z` is outside the spec grammar.
  if (DATE_ONLY.test(s)) return s + 'T00:00:00Z';
  return HAS_TZ.test(s) ? s : s + 'Z';
}

/** Parse a server timestamp as UTC unless it carries its own offset. Invalid Date (never a
 *  throw) for anything unparseable, including a runtime null. */
export function parseUTC(dateStr: string): Date {
  if (typeof dateStr !== 'string') return new Date(NaN);
  const raw = dateStr.trim();
  // Not an ISO calendar date: not this helper's format — hand it to the engine untouched.
  if (!ISO_START.test(raw)) return new Date(raw);
  return new Date(normalizeTimestamp(raw));
}

/**
 * Order server timestamps OLDEST first, unknowns last:
 * `rows.sort((a, b) => compareTimestampsAsc(a.ts, b.ts))`.
 *
 * Unknowns compare equal to each other and after every valid row, so no `NaN` ever reaches the
 * return value (a `NaN` comparator result makes the sort non-transitive).
 */
export function compareTimestampsAsc(a: string | null | undefined, b: string | null | undefined): number {
  const ka = a == null ? NaN : parseUTC(a).getTime();
  const kb = b == null ? NaN : parseUTC(b).getTime();
  const aUnknown = Number.isNaN(ka);
  const bUnknown = Number.isNaN(kb);
  if (aUnknown || bUnknown) return aUnknown && bUnknown ? 0 : aUnknown ? 1 : -1;
  return ka - kb;
}
