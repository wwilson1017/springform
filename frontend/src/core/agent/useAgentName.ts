import { useEffect, useSyncExternalStore } from 'react';
import { fetchJson } from '../api/client';
import type { AgentStatus } from './types';

/** The name a fresh install gives its assistant; the one place the UI may spell it. */
export const DEFAULT_AGENT_NAME = 'Whisk';

/**
 * The default agent's name (GET /api/agent/status `name`), fetched once and shared by the nav and
 * every card, the way useWorkspace shares the install name. Renaming in Settings calls
 * `setAgentName`, so every reader updates at once.
 */
let name: string | null = null;
let loading: Promise<void> | null = null;
const listeners = new Set<() => void>();

export function setAgentName(next: string) {
  name = next;
  for (const listener of listeners) listener();
}

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}

/** The default name until the first answer; a failed load is retried by the next component that mounts. */
export function useAgentName(): string {
  const current = useSyncExternalStore(subscribe, () => name);
  useEffect(() => {
    if (name || loading) return;
    loading = fetchJson<AgentStatus>('/api/agent/status')
      .then(
        (s) => setAgentName(s.name),
        () => {},
      )
      .finally(() => {
        loading = null;
      });
  }, []);
  return current || DEFAULT_AGENT_NAME;
}

/** The name as an element, for places that take a node rather than call a hook (nav labels). */
export function AgentName() {
  return useAgentName();
}
