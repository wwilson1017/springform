// @vitest-environment jsdom
//
// The undo queue is per-owner.
//
// `undoQueue.ts` is module state so a queued row survives TodoShell's remount on
// every tab switch. The owner is the list id the session pinned; the queue filters
// by it during render, so a row queued under one list can never paint for another.
//
// Lives in its own file because it needs the REAL `useTodoMeta`, which
// `undoPill.test.tsx` mocks away.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { getFiltersMock, listProjectsMock } = vi.hoisted(() => ({
  getFiltersMock: vi.fn(),
  listProjectsMock: vi.fn(),
}));
vi.mock('./api', () => ({ getFilters: getFiltersMock, listProjects: listProjectsMock }));

import type { Todo } from './types';
import { queueUndo, resetUndoQueue, useUndoQueue } from './undoQueue';
import { useTodoMeta, useTodoOwner } from './useTodoMeta';
import { ITEM_EXTRA } from './testFixtures';

const TODO: Todo = { ...ITEM_EXTRA,
  id: 91, title: 'the previous occupant’s errand', notes: '', project_id: null,
  project_name: null, context: '', tags: [], status: 'next_action', star: false,
  due_date: null, repeat: '', auto_star_on_due: false, source: 'ui',
  created_at: '2026-09-14T12:00:00Z', updated_at: '2026-09-14T12:00:00Z', completed_at: null,
};

/** Stands in for a todo page: every one of them calls `useTodoMeta`, and
 *  `TodoShell` renders the pill. */
function Page() {
  useTodoMeta();
  const entries = useUndoQueue(useTodoOwner());
  return <p data-testid="rows">{entries.map(e => e.title).join('|') || 'empty'}</p>;
}

/** Reads the queue as somebody else, with no effect involved — this is the half
 *  that has to hold in the very first render after the tab changes hands. */
function AsOtherOwner() {
  const entries = useUndoQueue('99');
  return <p data-testid="rows">{entries.map(e => e.title).join('|') || 'empty'}</p>;
}

let container: HTMLDivElement;
let root: Root;
const shown = () => container.querySelector('[data-testid="rows"]')?.textContent;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  getFiltersMock.mockReset().mockResolvedValue({ contexts: [], tags: [], status_counts: {} });
  listProjectsMock.mockReset().mockResolvedValue([]);
  resetUndoQueue();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  resetUndoQueue();
});

describe('undo queue ownership', () => {
  it('shows a mismatched owner nothing during render, before any effect runs', async () => {
    await act(async () => { root.render(<Page />); });
    act(() => { queueUndo(TODO); });
    expect(shown()).toBe('the previous occupant’s errand');

    // The filter is in the snapshot read, so the very first paint for a different
    // owner is already empty — an effect-time cleanup would show one frame.
    await act(async () => { root.render(<AsOtherOwner />); });

    expect(shown()).toBe('empty');
  });

  it('keeps them across a re-render for the SAME owner, which is why the queue is module state', async () => {
    await act(async () => { root.render(<Page />); });
    act(() => { queueUndo(TODO); });

    // What a tab switch looks like: the shell unmounts and a new page mounts.
    await act(async () => { root.unmount(); });
    root = createRoot(container);
    await act(async () => { root.render(<Page />); });

    expect(shown()).toBe('the previous occupant’s errand');
  });
});
