/**
 * Choosing and naming users. GET /api/core/timeline/mentionable?q= lists active people as
 * `{id, name}` (matching name or email, at most 20) to members too, so it serves every user
 * picker. Every answer feeds one name cache, so a stored id reads as a name wherever it shows.
 */
import { useEffect, useState } from 'react';
import { fetchJson } from '../core/api/client';
import type { UserRef } from '../core/api/types';

const names = new Map<number, string>();
let directory: Promise<void> | null = null;

export function searchUsers(q: string, signal?: AbortSignal): Promise<UserRef[]> {
  return fetchJson<UserRef[]>(`/api/core/timeline/mentionable?${new URLSearchParams({ q })}`, signal).then(list => {
    for (const u of list) names.set(u.id, u.name);
    return list;
  });
}

/** The cached name for an id, if any answer so far carried it. */
export const knownName = (id: number): string | undefined => names.get(id);

/**
 * `nameOf(id)` for display: a name the cache holds, else "User #id". An id the cache lacks loads
 * the directory's first page once per page load.
 *
 * simplification: past the first 20 people, an id nobody has searched for reads "User #id";
 * upgrade path: the record's API answers the name beside the id (a deal's owner_name does).
 */
export function useUserNames(ids: ReadonlyArray<number | null | undefined>): (id: number) => string {
  const [, setLoaded] = useState(0);
  const missing = ids.some(id => id != null && !names.has(id));
  useEffect(() => {
    if (!missing) return;
    let live = true;
    directory ??= searchUsers('').then(() => {}, () => { directory = null; });
    void directory.then(() => { if (live) setLoaded(n => n + 1); });
    return () => { live = false; };
  }, [missing]);
  return id => names.get(id) ?? `User #${id}`;
}

/** Forget every cached name. For tests: the cache is module state that outlives a render. */
export function resetUserNames(): void {
  names.clear();
  directory = null;
}
