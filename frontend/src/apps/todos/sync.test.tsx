// The change feed: what arrives every 30 s is folded into the list on screen (sync.ts), and a
// tombstone takes a row away for good. Both halves are invisible to tsc: a list that ignores a
// tombstone keeps showing a todo its owner just made private, and a poll that never stops keeps
// spending requests in a background tab.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { getChangesMock } = vi.hoisted(() => ({ getChangesMock: vi.fn() }));
vi.mock('./api', () => ({ getChanges: getChangesMock, listTodos: vi.fn(), updateTodo: vi.fn() }));

import { useTodos } from './hooks';
import { applyChanges, resetFeed, SYNC_MS, toBatch, useChangeFeed, type FeedBatch } from './sync';
import { ITEM_EXTRA } from './testFixtures';
import type { Changes, Todo } from './types';

const AT = '2026-10-01T12:00:00Z';
const todo = (id: number, over: Partial<Todo> = {}): Todo => ({
  ...ITEM_EXTRA, id, title: `todo ${id}`, notes: '', project_id: null, project_name: null, context: '',
  tags: [], status: 'inbox', star: false, due_date: null, repeat: '', auto_star_on_due: false,
  source: 'ui', created_at: `2026-10-01T12:00:0${id}Z`, updated_at: AT, completed_at: null, ...over,
});

const batch = (over: Partial<FeedBatch> = {}): FeedBatch =>
  ({ reset: false, items: [], removed: [], containers: false, ...over });

const page = (over: Partial<Changes> = {}): Changes => ({
  since_rev: 0, next_since_rev: 0, more: false, reset: false, changed: false, items: [], projects: [], areas: [],
  removed: { items: [], projects: [], areas: [] }, ...over,
});

const inbox = (t: Todo) => t.status === 'inbox';

describe('applyChanges', () => {
  it('drops a row whose tombstone arrives, and leaves the rest as they were', () => {
    const rows = [todo(1), todo(2), todo(3)];
    expect(applyChanges(rows, batch({ removed: [2] }), inbox)!.map(t => t.id)).toEqual([1, 3]);
    // A tombstone for a row this list never had changes nothing, not even the array.
    expect(applyChanges(rows, batch({ removed: [99] }), inbox)).toBe(rows);
  });

  it('replaces a row in place, lets one that no longer matches leave, and lets a new match join in order', () => {
    const rows = [todo(1), todo(3)];
    const next = applyChanges(rows, batch({
      items: [todo(1, { title: 'renamed' }), todo(3, { status: 'next_action' }), todo(2), todo(4, { status: 'done' })],
    }), inbox)!;
    expect(next.map(t => [t.id, t.title])).toEqual([[1, 'renamed'], [2, 'todo 2']]);
  });

  it('asks for a refetch when it cannot tell what belongs (a list the server computes)', () => {
    expect(applyChanges([todo(1)], batch({ items: [todo(5)] }))).toBeNull();
    expect(applyChanges([todo(1), todo(2)], batch({ removed: [1] }))!.map(t => t.id)).toEqual([2]);
  });

  it('folds the pages of one poll into a batch', () => {
    const b = toBatch([
      page({ items: [todo(1)], removed: { items: [{ id: 7, rev: 3 }], projects: [], areas: [] } }),
      page({ reset: true, projects: [] }),
    ]);
    expect(b).toEqual({ reset: true, items: [todo(1)], removed: [7], containers: false });
    expect(toBatch([page({ removed: { items: [], projects: [{ id: 1, rev: 2 }], areas: [] } })]).containers).toBe(true);
  });
});

let container: HTMLDivElement;
let root: Root;
let visibility: DocumentVisibilityState;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  visibility = 'visible';
  vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility);
  getChangesMock.mockReset();
  resetFeed();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/** A page holding the inbox, fed by the poll, as InboxPage is. */
function Harness({ rows, seen }: { rows: Todo[]; seen: (ids: number[]) => void }) {
  useChangeFeed('1');
  const { todos } = useTodos(() => Promise.resolve(rows), null, inbox);
  seen((todos ?? []).map(t => t.id));
  return null;
}

async function tick(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}

describe('useChangeFeed', () => {
  it('finds the cursor first, then applies upserts and tombstones every 30 s while visible', async () => {
    getChangesMock
      // The first walk: history the page already holds, in two pages of the journal.
      .mockResolvedValueOnce(page({ next_since_rev: 500, more: true, changed: true, items: [todo(9)] }))
      .mockResolvedValueOnce(page({ since_rev: 500, next_since_rev: 640, changed: true }))
      // Thirty seconds on: one todo arrives, one goes private elsewhere (a tombstone).
      .mockResolvedValueOnce(page({
        since_rev: 640, next_since_rev: 642, changed: true, items: [todo(3)],
        removed: { items: [{ id: 1, rev: 642 }], projects: [], areas: [] },
      }));
    let ids: number[] = [];
    await act(async () => { root.render(<Harness rows={[todo(1), todo(2)]} seen={v => { ids = v; }} />); });
    await tick(0);
    expect(getChangesMock.mock.calls.map(c => c[0])).toEqual([0, 500]);
    expect(ids).toEqual([1, 2]); // the walk's replay is not applied

    await tick(SYNC_MS);
    expect(getChangesMock).toHaveBeenLastCalledWith(640);
    expect(ids).toEqual([2, 3]);
  });

  it('skips the poll while the tab is hidden and catches up when it is shown', async () => {
    getChangesMock.mockResolvedValue(page({ next_since_rev: 5 }));
    await act(async () => { root.render(<Harness rows={[]} seen={() => {}} />); });
    await tick(0);
    expect(getChangesMock).toHaveBeenCalledTimes(1);

    visibility = 'hidden';
    await tick(SYNC_MS * 3);
    expect(getChangesMock).toHaveBeenCalledTimes(1);

    visibility = 'visible';
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); });
    await tick(0);
    expect(getChangesMock).toHaveBeenCalledTimes(2);
    expect(getChangesMock).toHaveBeenLastCalledWith(5);
  });

  it('refetches the page when the server says the cursor is no good', async () => {
    const rows = vi.fn(() => Promise.resolve([todo(1)]));
    function Refetching() {
      useChangeFeed('1');
      useTodos(rows, null, inbox);
      return null;
    }
    getChangesMock
      .mockResolvedValueOnce(page({ next_since_rev: 9 }))
      .mockResolvedValueOnce(page({ since_rev: 9, next_since_rev: 2, reset: true, changed: true, items: [todo(1)] }));
    await act(async () => { root.render(<Refetching />); });
    await tick(0);
    expect(rows).toHaveBeenCalledTimes(1);
    await tick(SYNC_MS);
    expect(rows).toHaveBeenCalledTimes(2);
  });
});
