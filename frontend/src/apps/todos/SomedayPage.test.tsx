// @vitest-environment jsdom
//
// Someday's two controls: the context filter, and "→ Next" — the one-click way to commit
// to an idea. Neither is visible to tsc: a filter wired to the wrong field still compiles,
// and so does a button that writes the wrong status or never reloads the list.
//
// createRoot + React act, following the repo's other component tests — no RTL.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { listTodosMock, updateTodoMock } = vi.hoisted(() => ({
  listTodosMock: vi.fn(),
  updateTodoMock: vi.fn(),
}));
vi.mock('./api', () => ({
  listTodos: listTodosMock,
  updateTodo: updateTodoMock,
  createTodo: vi.fn(),
  listProjects: vi.fn().mockResolvedValue([]),
  getFilters: vi.fn().mockResolvedValue({ contexts: ['@Home', '@calls'], tags: [], status_counts: {} }),
}));

import { SomedayPage } from './SomedayPage';
import type { Todo } from './types';
import { queueUndo, resetUndoQueue } from './undoQueue';
import { ITEM_EXTRA } from './testFixtures';

const base: Omit<Todo, 'id' | 'title'> = { ...ITEM_EXTRA,
  notes: '', project_id: null, project_name: null, context: '', tags: [],
  status: 'someday_maybe', star: false, due_date: null, repeat: '',
  auto_star_on_due: false, source: 'ui',
  created_at: '2026-08-06T12:00:00Z', updated_at: '2026-08-06T12:00:00Z', completed_at: null,
};
const ROW: Todo = { ...base, id: 1, title: 'learn to row', context: '@home' };
const CALL: Todo = { ...base, id: 2, title: 'call the boat club', context: '@calls' };
// Its bring-back date is long past, so it sits in the "Time to revisit" section.
const BACK: Todo = { ...base, id: 3, title: 'plan the garden', revisit_on: '2026-01-01' };

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  listTodosMock.mockReset().mockResolvedValue([ROW, CALL, BACK]);
  updateTodoMock.mockReset().mockResolvedValue(ROW);
  resetUndoQueue();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  resetUndoQueue();
});

async function render() {
  await act(async () => {
    root.render(<MemoryRouter><SomedayPage /></MemoryRouter>);
  });
  await act(async () => { await Promise.resolve(); });
}

const titles = () => [...container.querySelectorAll('p.break-words')].map(p => p.textContent);
const button = (label: string) =>
  [...container.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent?.trim() === label);
const nextButtons = () =>
  [...container.querySelectorAll<HTMLButtonElement>('button')].filter(b => b.textContent?.trim() === '→ Next');
const click = (el: Element) => act(async () => { (el as HTMLElement).click(); });

describe('SomedayPage — context filter', () => {
  it('narrows the list to the chosen context, whatever case it was typed in', async () => {
    await render();
    expect(titles()).toEqual(['plan the garden', 'learn to row', 'call the boat club']);

    await click(button('Filters')!);
    // The chip keeps the casing the context list has; the row was filed as "@home".
    await click(button('@Home')!);
    expect(titles()).toEqual(['learn to row']);
    expect(container.textContent).toContain('1 of 3 item');

    await click(button('Clear filters')!);
    expect(titles()).toHaveLength(3);
  });
});

describe('SomedayPage — → Next', () => {
  it('offers the move on every row, the revisit section included', async () => {
    await render();
    expect(nextButtons()).toHaveLength(3);
  });

  it('moves the idea to next actions and drops it from the list', async () => {
    await render();
    listTodosMock.mockResolvedValue([CALL, BACK]); // the server's list once the move lands
    const row = [...container.querySelectorAll('div.flex.items-start.gap-2')]
      .find(d => d.textContent?.includes('learn to row'))!;
    await click(row.querySelector<HTMLButtonElement>('button[title^="Commit to this"]')!);

    expect(updateTodoMock).toHaveBeenCalledTimes(1);
    expect(updateTodoMock).toHaveBeenCalledWith(1, { status: 'next_action' });
    expect(titles()).toEqual(['plan the garden', 'call the boat club']);
  });

  it('retires a pending undo for that todo, which would otherwise put it back', async () => {
    await render();
    act(() => { queueUndo({ ...ROW, status: 'inbox' }, 'filed'); });
    expect(container.querySelector('[aria-label="Recent changes you can undo"]')).not.toBeNull();

    await click(nextButtons()[1]); // "learn to row": the first row after the revisit section
    expect(updateTodoMock).toHaveBeenCalledWith(1, { status: 'next_action' });
    expect(container.querySelector('[aria-label="Recent changes you can undo"]')).toBeNull();
  });
});
