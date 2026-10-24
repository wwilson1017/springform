// @vitest-environment jsdom
//
// The half of the context rename that does NOT live in ContextRename: where the
// Contexts tab offers it and what it does afterwards. Both are silent if they break —
// a context only finished to-dos carry would have no control at all, and the filter
// would keep pointing at a context that no longer exists, leaving an empty page.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { listTodosMock, getFiltersMock, renameContextMock } = vi.hoisted(() => ({
  listTodosMock: vi.fn(),
  getFiltersMock: vi.fn(),
  renameContextMock: vi.fn(),
}));
vi.mock('./api', () => ({
  listTodos: listTodosMock,
  updateTodo: vi.fn(),
  todayTodos: vi.fn().mockResolvedValue([]),
  createTodo: vi.fn(),
  listProjects: vi.fn().mockResolvedValue([]),
  createProject: vi.fn(),
  updateProject: vi.fn(),
  getFilters: getFiltersMock,
  renameContext: renameContextMock,
  getCaptureLink: vi.fn(),
  regenerateCaptureLink: vi.fn(),
}));

import { SearchPage } from './SearchPage';
import type { Todo } from './types';
import { ITEM_EXTRA } from './testFixtures';

const BAKE: Todo = { ...ITEM_EXTRA,
  id: 1, title: 'Order flour', notes: '', project_id: null, project_name: null,
  context: '@Baking', tags: [], status: 'next_action', star: false, due_date: null,
  repeat: '', auto_star_on_due: false, source: 'ui',
  created_at: '2026-08-06T12:00:00Z', updated_at: '2026-08-06T12:00:00Z', completed_at: null,
};
const filters = (contexts: string[]) => ({ contexts, tags: [], status_counts: {} });

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  listTodosMock.mockReset().mockImplementation(
    ({ status }: { status?: string }) => Promise.resolve(status === 'next_action' ? [BAKE] : []),
  );
  getFiltersMock.mockReset().mockResolvedValue(filters(['@Baking', 'Old']));
  renameContextMock.mockReset().mockResolvedValue({});
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render() {
  await act(async () => { root.render(<MemoryRouter><SearchPage /></MemoryRouter>); });
  await act(async () => {});
}

const renameButtons = () =>
  [...container.querySelectorAll('button')].filter(b => b.textContent === 'Rename');
const filterSelect = () =>
  container.querySelector<HTMLSelectElement>('select[aria-label="Filter by context"]')!;

function setValue(el: HTMLInputElement | HTMLSelectElement, value: string, event: string) {
  const proto = el instanceof HTMLSelectElement ? HTMLSelectElement : HTMLInputElement;
  Object.getOwnPropertyDescriptor(proto.prototype, 'value')!.set!.call(el, value);
  el.dispatchEvent(new Event(event, { bubbles: true }));
}

describe('SearchPage context rename', () => {
  it('offers Rename on a context group and the filter follows the new name', async () => {
    await render();
    act(() => { setValue(filterSelect(), '@Baking', 'change'); });
    expect(renameButtons().map(b => b.getAttribute('aria-label')))
      .toEqual(['Rename context @Baking']);

    act(() => { renameButtons()[0].click(); });
    act(() => { setValue(container.querySelector('input[aria-label^="New name"]')!, 'Baking', 'input'); });
    getFiltersMock.mockResolvedValue(filters(['Baking', 'Old']));
    listTodosMock.mockImplementation(({ status }: { status?: string }) =>
      Promise.resolve(status === 'next_action' ? [{ ...BAKE, context: 'Baking' }] : []));
    await act(async () => {
      [...container.querySelectorAll('button')].find(b => b.textContent === 'Save')!.click();
    });
    await act(async () => {});

    expect(renameContextMock).toHaveBeenCalledWith('@Baking', 'Baking', false);
    expect(filterSelect().value).toBe('Baking');
    expect(container.textContent).toContain('Order flour');
  });

  it('offers Rename beside the filter for a context no open to-do carries', async () => {
    await render();
    act(() => { setValue(filterSelect(), 'Old', 'change'); });
    expect(renameButtons().map(b => b.getAttribute('aria-label')))
      .toEqual(['Rename context Old']);
  });

  it('offers no Rename on the "No context" group', async () => {
    listTodosMock.mockImplementation(({ status }: { status?: string }) =>
      Promise.resolve(status === 'next_action' ? [{ ...BAKE, context: '' }] : []));
    await render();
    expect(container.textContent).toContain('No context');
    expect(renameButtons()).toEqual([]);
  });
});
