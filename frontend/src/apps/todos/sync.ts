// The change feed: what other people (and other tabs, and Whisk) changed, every 30 s while the
// tab is visible. GET /changes?since_rev= answers the rows the user can see, whole, and a
// tombstone ({id, rev}) for each row that left their view (deleted, made private by its owner,
// given away). Pages apply a batch to the list on screen (`applyChanges`); `reset` means the
// cursor is no good any more and every page refetches.
import { useEffect } from 'react';
import { getChanges, getChangesHead } from './api';
import type { Changes, Todo } from './types';

export const SYNC_MS = 30_000;

export interface FeedBatch {
  /** The cursor predates a reset: drop every cached row and refetch. */
  reset: boolean;
  items: Todo[];
  /** Ids of todos the user can no longer see. */
  removed: number[];
  /** A project or area changed or went away (names on rows, pickers, counts). */
  containers: boolean;
}

type Listener = (batch: FeedBatch) => void;
const listeners = new Set<Listener>();

export function subscribeFeed(listener: Listener): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** Hand a batch to every page listening. Exported for tests. */
export function publishFeed(batch: FeedBatch) {
  listeners.forEach(l => l(batch));
}

/** Fold one page of the feed into a batch. */
export function toBatch(pages: Changes[]): FeedBatch {
  return {
    reset: pages.some(p => p.reset),
    items: pages.flatMap(p => p.items),
    removed: pages.flatMap(p => p.removed.items.map(r => r.id)),
    containers: pages.some(p => p.projects.length + p.areas.length
      + p.removed.projects.length + p.removed.areas.length > 0),
  };
}

/** Open lists read oldest first, as the server orders them (created_at, then id). */
export const byCreated = (a: Todo, b: Todo) =>
  a.created_at === b.created_at ? a.id - b.id : a.created_at < b.created_at ? -1 : 1;

/**
 * The list on screen after a batch, or null when only a refetch can tell. A tombstone drops its
 * row; an upsert replaces its row in place. With `matches` (the page's own filter, in the
 * client) an upsert that no longer matches leaves and a new one that does joins, in `order`.
 * Without it the list is one the server computes (Today), so an upsert touching it, or one that
 * might belong in it, asks for a refetch.
 */
export function applyChanges(
  rows: Todo[], batch: FeedBatch, matches?: (t: Todo) => boolean, order: (a: Todo, b: Todo) => number = byCreated,
): Todo[] | null {
  const gone = new Set(batch.removed);
  if (!matches) return batch.items.length > 0 ? null : rows.filter(r => !gone.has(r.id));
  const fresh = new Map(batch.items.map(t => [t.id, t]));
  const kept = rows.filter(r => !gone.has(r.id) && !fresh.has(r.id));
  const touched = rows.filter(r => fresh.has(r.id)).map(r => fresh.get(r.id)!).filter(matches);
  const known = new Set(rows.map(r => r.id));
  const joined = batch.items.filter(t => !known.has(t.id) && !gone.has(t.id) && matches(t));
  if (touched.length === 0 && joined.length === 0) {
    return kept.length === rows.length ? rows : kept; // unchanged keeps its identity: no re-render
  }
  return [...kept, ...touched, ...joined].sort(order);
}

let cursor: number | null = null;
let cursorOwner = '';

/**
 * Poll the feed for `owner` (the signed-in user's id; '' = nobody) every SYNC_MS while the tab is
 * visible, and at once when it becomes visible again. The first poll only asks for the head (the
 * current rev): the pages have just loaded everything before it.
 */
export function useChangeFeed(owner: string, onBatch?: (batch: FeedBatch) => void) {
  useEffect(() => {
    if (!owner) return;
    if (cursorOwner !== owner) { cursor = null; cursorOwner = owner; }
    let cancelled = false;
    let running = false;
    const tick = async () => {
      if (running || cancelled || document.visibilityState !== 'visible') return;
      running = true;
      try {
        if (cursor === null) {
          const head = await getChangesHead();
          if (!cancelled && cursorOwner === owner) cursor = head.next_since_rev;
          return;
        }
        const pages: Changes[] = [];
        let since = cursor;
        for (;;) {
          const page = await getChanges(since);
          if (cancelled || cursorOwner !== owner) return;
          pages.push(page);
          since = page.next_since_rev;
          if (!page.more) break;
        }
        cursor = since;
        const batch = toBatch(pages);
        if (batch.reset || pages.some(p => p.changed)) {
          publishFeed(batch);
          onBatch?.(batch);
        }
      } catch {
        // Offline or mid-deploy: the next tick asks again from the same cursor.
      } finally {
        running = false;
      }
    };
    void tick();
    const timer = setInterval(() => void tick(), SYNC_MS);
    const onVisible = () => void tick();
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      cancelled = true;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [owner, onBatch]);
}

/** Forget the cursor. For tests: it is module state that outlives a render. */
export function resetFeed() {
  cursor = null;
  cursorOwner = '';
}
