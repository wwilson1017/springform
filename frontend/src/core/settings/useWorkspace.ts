import { useEffect, useSyncExternalStore } from 'react';
import { fetchJson } from '../api/client';
import type { Workspace } from './types';

/**
 * The install's name, timezone, version and preview flag (GET /api/core/workspace), fetched once
 * and shared by the header and the Workspace card. A module-level store rather than a context, so
 * the header needs no provider; `setWorkspace` after a save updates every reader at once.
 */
let workspace: Workspace | null = null;
let loading: Promise<void> | null = null;
const listeners = new Set<() => void>();

// index.html's title, until the install name replaces it.
const DEFAULT_TITLE = document.title;

export function setWorkspace(next: Workspace) {
  // The tab shows the install name, unless a page has set a title of its own (Todos does).
  if (document.title === (workspace?.name ?? DEFAULT_TITLE)) document.title = next.name;
  workspace = next;
  for (const listener of listeners) listener();
}

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}

/** null until the first answer; a failed load is retried by the next component that mounts. */
export function useWorkspace(): Workspace | null {
  const current = useSyncExternalStore(subscribe, () => workspace);
  useEffect(() => {
    if (workspace || loading) return;
    loading = fetchJson<Workspace>('/api/core/workspace')
      .then(setWorkspace, () => {})
      .finally(() => {
        loading = null;
      });
  }, []);
  return current;
}
