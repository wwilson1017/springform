// Todo GTD — shared meta (status counts, contexts, tags, projects, time zone).
//
// The app uses flat sibling routes (no in-app Outlet layout), so the shell
// unmounts on every tab switch. A module-level stale-while-revalidate cache
// keeps the tab badges and dropdowns from flashing empty on each switch:
// cached meta renders instantly, a background refetch follows, and every
// mutation calls refreshMeta() to keep the inbox badge honest.
//
// The cache is keyed by the signed-in user's id, so a snapshot fetched for one person can never be
// served for another (a sign-out and sign-in in the same tab), even as a flash.
import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';
import { getFilters, listProjects } from './api';
import { useMe } from './me';
import { setUndoOwner } from './undoQueue';
import type { TodoFilters, TodoProject } from './types';

export interface TodoMeta {
  filters: TodoFilters | null;
  projects: TodoProject[];
  loaded: boolean;
}

const EMPTY: TodoMeta = { filters: null, projects: [], loaded: false };
let cache: TodoMeta = EMPTY;
let cacheOwner = '';
const listeners = new Set<(m: TodoMeta) => void>();
let inflight: Promise<void> | null = null;
let inflightOwner = '';
// At most one follow-up fetch chained behind `inflight` — see refreshMeta.
let queued: Promise<void> | null = null;

async function fetchMeta(owner: string): Promise<void> {
  try {
    const [filters, projects] = await Promise.all([getFilters(), listProjects()]);
    // Commit only if the owner hasn't changed mid-flight: a late response
    // fetched for a PREVIOUS user must neither overwrite the new owner's cache
    // nor be shown to them.
    if (cacheOwner === owner) {
      cache = { filters, projects, loaded: true };
      listeners.forEach(l => l(cache));
    }
  } catch {
    // stale-while-revalidate: keep the last good snapshot on a failed refresh
  }
}

function startFetch(): Promise<void> {
  const owner = cacheOwner;
  inflightOwner = owner;
  const p: Promise<void> = fetchMeta(owner).then(() => {
    if (inflight === p) inflight = null;
  });
  inflight = p;
  return p;
}

/** Module-level so mutation helpers (hooks.ts) can revalidate without a
 * component handle. The owner is re-read from the last useTodoMeta mount.
 * An in-flight fetch is reused only for the SAME owner — an account switch
 * mid-flight starts a fresh fetch instead of stranding the new account
 * waiting on a result that will be discarded.
 *
 * A refresh asked for WHILE one is in flight does NOT join it. Every caller is
 * a mutation saying "something changed just now", and the running fetch may
 * already have read its half of the data before that write committed —
 * `getFilters()` and `listProjects()` resolve independently, so the slower one
 * decides when the pair commits. Joining it can therefore install a snapshot
 * that predates the change: a project created mid-fetch stays missing from the
 * dropdown, which TriageCard's recovery toast explicitly tells the user to pick
 * from, and the select can hold a project_id with no matching option. So chain
 * exactly ONE follow-up — a burst of mutations collapses into a single extra
 * fetch rather than one per call. */
export function refreshMeta(): Promise<void> {
  if (inflight && inflightOwner === cacheOwner) {
    if (!queued) {
      queued = inflight.then(() => { queued = null; return startFetch(); });
    }
    return queued;
  }
  return startFetch();
}

/** Whose todos these are: the signed-in user's id ('' before /api/me answers).
 *  ONE definition, because the meta cache and the undo queue must agree about
 *  whose a row is. */
export function useTodoOwner(): string {
  return String(useMe().id ?? '');
}

function subscribeMeta(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => { listeners.delete(onChange); };
}

/** The user's IANA time zone, as the server reads it (undefined until the first filters payload
 *  lands). "Today" is the server's answer, not whichever browser is looking: the server, the web
 *  app and Whisk must agree on it. Subscribes to the meta
 *  cache without triggering a fetch — the shell on every page already does that. */
export function useListTz(): string | undefined {
  return useSyncExternalStore(subscribeMeta, () => cache.filters?.tz, () => undefined);
}

/** Every project the user can see, on the same no-fetch subscription. */
export function useListProjects(): TodoProject[] {
  return useSyncExternalStore(subscribeMeta, () => cache.projects, () => cache.projects);
}

/** The filters payload (people, areas, contexts…), on the same no-fetch
 *  subscription — for components inside a page, like the edit sheet. */
export function useListFilters(): TodoFilters | null {
  return useSyncExternalStore(subscribeMeta, () => cache.filters, () => null);
}

export function useTodoMeta(): TodoMeta & { refreshMeta: () => Promise<void> } {
  const owner = useTodoOwner();
  // Snapshot carries the owner it was built for; the render-time guard below
  // refuses to serve a mismatched snapshot, so no effect-time setState is
  // needed to blank stale data — it simply never renders.
  const [snap, setSnap] = useState<{ owner: string; meta: TodoMeta }>(
    () => ({ owner: cacheOwner, meta: cache }),
  );

  useEffect(() => {
    const listener = (m: TodoMeta) => setSnap({ owner: cacheOwner, meta: m });
    listeners.add(listener);
    if (cacheOwner !== owner) {
      // A different user than the cache was built for: drop the module cache
      // before revalidating.
      cache = EMPTY;
      cacheOwner = owner;
      // ...and the pending undo rows with it. They are module state for the
      // same reason this cache is, so a row queued under another user must go
      // rather than linger as a button whose revert the server would refuse.
      setUndoOwner(owner);
    }
    void refreshMeta(); // render cached instantly, revalidate in background
    return () => { listeners.delete(listener); };
  }, [owner]);

  const refresh = useCallback(() => refreshMeta(), []);
  const meta = snap.owner === owner ? snap.meta : EMPTY;
  return { ...meta, refreshMeta: refresh };
}
