// Mine or everyone's: which todos the working lists (Inbox, To Do, Waiting, Someday, Done) show.
// "Mine" is the server's work scope (`mine=true`): your private todos, team todos assigned to you
// and unassigned team todos, the same set Today, the review and the launcher badge count.
// Remembered per browser; module state so the choice survives the shell remounting per page.
import { useSyncExternalStore } from 'react';
import type { Todo } from './types';

export type Scope = 'mine' | 'all';

const KEY = 'springform.todos.scope';
const listeners = new Set<() => void>();

function read(): Scope {
  try {
    return localStorage.getItem(KEY) === 'all' ? 'all' : 'mine';
  } catch {
    return 'mine';
  }
}

let scope: Scope = read();

export function setScope(next: Scope) {
  scope = next;
  try { localStorage.setItem(KEY, next); } catch { /* private mode: the choice lasts this tab */ }
  listeners.forEach(l => l());
}

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  return () => { listeners.delete(onChange); };
}

export function useScope(): Scope {
  return useSyncExternalStore(subscribe, () => scope);
}

/** The server's WORK rule (service.py), for rows the change feed delivers. */
export function isMine(t: Pick<Todo, 'visibility' | 'owner_user_id' | 'assignee_user_id'>, me: number | null): boolean {
  return t.visibility === 'private'
    ? t.owner_user_id === me
    : t.assignee_user_id === null || t.assignee_user_id === me;
}
