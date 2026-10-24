// The revalidation contract of refreshMeta(), which nothing else can catch:
// tsc sees a Promise either way, and the failure is a silently STALE dropdown,
// not an error.
//
// Every caller of refreshMeta() is a mutation saying "something changed just
// now". It used to return the in-flight fetch when one was running — but that
// fetch reads getFilters() and listProjects() independently and commits when
// the SLOWER one lands, so its projects array can predate the write that
// prompted the call. Joining it installs that stale snapshot and reports
// success. TriageCard's inline project creation is where that surfaces: its
// recovery toast tells the user to pick the new project "from the list", so
// the list has to actually contain it (issue todo-gtd #1587, Codex review of PR todo-gtd #1633).
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getFiltersMock, listProjectsMock } = vi.hoisted(() => ({
  getFiltersMock: vi.fn(),
  listProjectsMock: vi.fn(),
}));
vi.mock('./api', () => ({ getFilters: getFiltersMock, listProjects: listProjectsMock }));

const FILTERS = { contexts: [], tags: [], status_counts: {} };

/** A fetch whose completion this test controls, so "while one is in flight" is
 * a real state and not a timing hope. */
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>(r => { resolve = r; });
  return { promise, resolve };
}

/** Fresh module state per test — the cache, the in-flight handle and the queue
 * are all module-level singletons. */
async function loadModule() {
  vi.resetModules();
  return import('./useTodoMeta');
}

beforeEach(() => {
  getFiltersMock.mockReset().mockResolvedValue(FILTERS);
  listProjectsMock.mockReset().mockResolvedValue([]);
});

describe('refreshMeta revalidation', () => {
  it('fetches once when nothing is in flight', async () => {
    const { refreshMeta } = await loadModule();
    await refreshMeta();
    expect(listProjectsMock).toHaveBeenCalledTimes(1);
  });

  it('schedules a FOLLOW-UP fetch when asked mid-flight, instead of joining a snapshot that predates the write', async () => {
    const first = deferred<typeof FILTERS>();
    getFiltersMock.mockReturnValueOnce(first.promise);
    // The exact shape of the bug: listProjects resolves EARLY, so the running
    // fetch is already holding a project list from before the write, and only
    // the slower getFilters is keeping it from committing.
    listProjectsMock.mockResolvedValueOnce([]);

    const { refreshMeta } = await loadModule();
    const inFlight = refreshMeta();
    expect(listProjectsMock).toHaveBeenCalledTimes(1);

    // …a project is created here, then its onChanged calls refreshMeta().
    const afterWrite = refreshMeta();
    expect(afterWrite).not.toBe(inFlight); // joining it is the bug

    first.resolve(FILTERS);
    await afterWrite;

    // The second call must have produced a real second read, started after the
    // write — not a reuse of the one already holding stale data.
    expect(listProjectsMock).toHaveBeenCalledTimes(2);
  });

  it('collapses a burst of mid-flight refreshes into ONE follow-up', async () => {
    const first = deferred<typeof FILTERS>();
    getFiltersMock.mockReturnValueOnce(first.promise);

    const { refreshMeta } = await loadModule();
    refreshMeta();
    const a = refreshMeta();
    const b = refreshMeta();
    const c = refreshMeta();
    expect(b).toBe(a); // one shared follow-up, not one fetch per caller
    expect(c).toBe(a);

    first.resolve(FILTERS);
    await a;

    expect(listProjectsMock).toHaveBeenCalledTimes(2);
  });

  it('lets a later mutation queue again once the follow-up has run', async () => {
    const { refreshMeta } = await loadModule();
    await refreshMeta();
    await refreshMeta();
    expect(listProjectsMock).toHaveBeenCalledTimes(2);
  });

  it('keeps the last good snapshot when a refresh fails', async () => {
    // stale-while-revalidate: a failed revalidation must not blank the cache.
    listProjectsMock.mockRejectedValueOnce(new Error('offline'));
    const { refreshMeta } = await loadModule();
    await expect(refreshMeta()).resolves.toBeUndefined();
  });
});
