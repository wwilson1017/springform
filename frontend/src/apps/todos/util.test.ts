import { describe, expect, it } from 'vitest';
import { daysSince, dueLabel, formatAge, matchesFilter, parseTags, todayStr, withOwnArea } from './util';

const TODO = {
  title: 'Call Val about the order',
  notes: 'invoice #42',
  context: '@calls',
  project_name: 'Bakery',
  tags: ['urgent'],
};

describe('matchesFilter', () => {
  it('empty search matches everything', () => {
    expect(matchesFilter(TODO, '')).toBe(true);
  });
  it('searches title, notes, context, project and tags', () => {
    for (const q of ['val', 'INVOICE', '@calls', 'bakery', 'urgent']) {
      expect(matchesFilter(TODO, q)).toBe(true);
    }
    expect(matchesFilter(TODO, 'freezer')).toBe(false);
  });
  // The context filter left this function in todo-gtd #1564 — it is `contextFacet.ts`'s `matchesContexts`
  // now (multi-select, still exact and case-insensitive), pinned in `collectionConfig.test.ts`.
});

describe('parseTags', () => {
  it('splits, trims, drops empties', () => {
    expect(parseTags(' a, b ,, c ')).toEqual(['a', 'b', 'c']);
  });
});

describe('todayStr / dueLabel', () => {
  const now = new Date(2026, 7, 1, 23, 30); // late evening local — no UTC drift
  it('todayStr is the LOCAL date', () => {
    expect(todayStr(now)).toBe('2026-08-01');
  });
  it('labels today/tomorrow/overdue', () => {
    const today = todayStr(now);
    expect(dueLabel('2026-08-01', today)).toEqual({ text: 'Today', overdue: false });
    expect(dueLabel('2026-08-02', today)).toEqual({ text: 'Tomorrow', overdue: false });
    expect(dueLabel('2026-07-30', today).overdue).toBe(true);
    expect(dueLabel('2026-08-10', today).overdue).toBe(false);
  });
});

describe('formatAge', () => {
  const now = new Date('2026-08-01T12:00:00Z');
  it('buckets into days/weeks/months', () => {
    expect(formatAge('2026-08-01T09:00:00Z', now)).toBe('today');
    expect(formatAge('2026-07-29T12:00:00Z', now)).toBe('3d');
    expect(formatAge('2026-07-10T12:00:00Z', now)).toBe('3w');
    expect(formatAge('2026-04-01T12:00:00Z', now)).toBe('4mo');
  });

  // `updated_at` is a Postgres TIMESTAMPTZ: `.isoformat()` emits SIX fraction digits and an
  // explicit offset, and ECMAScript guarantees parsing for exactly THREE. Bare `new Date()` read
  // this shape only because V8 is lenient; Safari — which `vite.config.ts` targets — need not be,
  // and an Invalid Date here rendered the age chip as "NaNmo" (todo-gtd #1462).
  it('reads the six-fraction-digit shape Postgres actually emits', () => {
    // An hour clear of the 3d boundary — the fractional seconds must not decide the bucket.
    expect(formatAge('2026-07-29T11:00:00.123456+00:00', now)).toBe('3d');
  });

  // The test above cannot FAIL on a revert: vitest runs on V8, which parses six fraction digits
  // natively, so it stays green with `new Date()` restored. This one is the guard. An offset-free
  // timestamp is where V8 itself diverges — bare `new Date()` reads it as LOCAL (vitest pins
  // TZ=America/Chicago, so 12:00 becomes 17:00Z) while `parseUTC` reads it as UTC, five hours
  // apart and across the bucket boundary.
  it('treats an offset-free timestamp as UTC, not local', () => {
    expect(formatAge('2026-07-29T12:00:00', now)).toBe('3d'); // '2d' if parsed as local
  });
});

describe('daysSince', () => {
  // Drives the Review page's stale filter (>= STALE_DAYS).
  const now = new Date('2026-08-15T12:00:00Z');
  it('floors whole days from a ms delta', () => {
    expect(daysSince('2026-08-15T09:00:00Z', now)).toBe(0);
    expect(daysSince('2026-08-14T12:00:00Z', now)).toBe(1);
    expect(daysSince('2026-08-01T13:00:00Z', now)).toBe(13); // 13.96d floors to 13
    expect(daysSince('2026-08-01T12:00:00Z', now)).toBe(14); // exactly 14d
  });

  // The stale filter is `daysSince(...) >= STALE_DAYS`, and `NaN >= 14` is FALSE — so a timestamp
  // this cannot parse does not merely sort oddly, it DROPS the todo from the Review page entirely.
  // Parsing through `parseUTC` is what makes the six-digit Postgres shape safe on Safari (todo-gtd #1462).
  it('reads the six-fraction-digit shape Postgres actually emits', () => {
    expect(daysSince('2026-08-01T12:00:00.123456+00:00', now)).toBe(13); // 13.99d floors to 13
    expect(daysSince('2026-08-01T11:00:00.123456+00:00', now)).toBe(14);
  });

  // The revert guard, for the same reason as `formatAge`'s: V8 parses the six-digit shape either
  // way, but only `parseUTC` reads an offset-free timestamp as UTC. Parsed as local Central it
  // lands at 17:00Z — 13.79 days, which floors to 13 and falls below STALE_DAYS, i.e. the todo
  // silently drops off the Review page.
  it('treats an offset-free timestamp as UTC, not local', () => {
    expect(daysSince('2026-08-01T12:00:00', now)).toBe(14); // 13 if parsed as local
  });
});

describe('withOwnArea', () => {
  const areas = [{ id: 1, name: 'Home' }];
  it('adds a row\'s archived area, named or not, and leaves known/none alone', () => {
    expect(withOwnArea(areas, 2, 'Old')).toEqual([{ id: 2, name: 'Old' }, ...areas]);
    expect(withOwnArea(areas, 2, null)[0].name).toBe('Archived area');
    expect(withOwnArea(areas, 1, 'Home')).toBe(areas);
    expect(withOwnArea(areas, null)).toBe(areas);
  });
});
