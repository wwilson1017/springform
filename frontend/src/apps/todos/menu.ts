/**
 * The menu: ONE definition of the ten lists, read by the top menu and the phone bottom bar.
 * Array order is the display order everywhere.
 *
 * `tier` splits the top menu (primary = the lists you work from, secondary = visited less
 * often). `sub` is the path below the app's root ('' = Today); `todoPath` makes it absolute.
 */
export type ListKey =
  | 'today' | 'inbox' | 'next' | 'search' | 'projects'
  | 'areas' | 'waiting' | 'someday' | 'review' | 'done';

export interface ListItem {
  key: ListKey;
  label: string;
  sub: string;
  tier: 'primary' | 'secondary';
}

export const LISTS: ListItem[] = [
  { key: 'today', label: 'Today', sub: '', tier: 'primary' },
  { key: 'inbox', label: 'Inbox', sub: '/inbox', tier: 'primary' },
  { key: 'next', label: 'To Do', sub: '/next', tier: 'primary' },
  { key: 'search', label: 'Contexts', sub: '/search', tier: 'primary' },
  { key: 'projects', label: 'Projects', sub: '/projects', tier: 'primary' },
  { key: 'areas', label: 'Areas', sub: '/areas', tier: 'secondary' },
  { key: 'waiting', label: 'Waiting', sub: '/waiting', tier: 'secondary' },
  { key: 'someday', label: 'Someday', sub: '/someday', tier: 'secondary' },
  { key: 'review', label: 'Review', sub: '/review', tier: 'secondary' },
  { key: 'done', label: 'Done', sub: '/done', tier: 'secondary' },
];

export const PRIMARY = LISTS.filter(l => l.tier === 'primary');
export const SECONDARY = LISTS.filter(l => l.tier === 'secondary');

/** The app's root, as the manifest mounts it (`app.json` path). */
export const TODOS_ROOT = '/todos';

/** An absolute in-app path: `todoPath('/inbox')` is `/todos/inbox`. */
export const todoPath = (sub: string) => `${TODOS_ROOT}${sub}`;

/** Below this the primary lists move to a bottom bar: the core shell's mobile breakpoint. */
export const PHONE_QUERY = '(max-width: 767px)';

/**
 * Priority-plus overflow for the secondary items of the top menu.
 *
 * Returns the indices that move into "More". Items collapse from the right; the
 * current one (`current`, -1 if none of these is current) never does.
 *
 * `widths` are the items' full widths (their own padding included, no gap between
 * them), `available` is the room for the whole run, `moreWidth` the "More" button.
 */
export function overflowHidden(
  widths: number[], available: number, moreWidth: number, current: number,
): number[] {
  const total = widths.reduce((a, b) => a + b, 0);
  if (total <= available) return [];
  // Something must go, so "More" is showing and takes its share first; then the
  // current item, which stays whatever happens.
  let used = moreWidth + (current >= 0 ? widths[current] : 0);
  const hidden: number[] = [];
  let full = false;
  widths.forEach((w, i) => {
    if (i === current) return;
    if (!full && used + w <= available) used += w;
    else { full = true; hidden.push(i); }
  });
  return hidden;
}
