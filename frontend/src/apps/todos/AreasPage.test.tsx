// @vitest-environment jsdom
//
// The Areas page: each active area with what is live under it.
//
// The grouping is the page, and none of it is visible to tsc: that a project lands
// under the area it names, that a todo lands under the area it SHOWS under (its own,
// else its project's — `effective_area_id`, never the raw `area_id`), that next
// actions and someday items are kept apart, and that an archived area leaves the
// cards but stays restorable. Then the writes: add, the refusal that keeps what was
// typed, rename, archive, restore — and no way to delete.
//
// createRoot + React 19 act, following ProjectDetailPage.inline.test.tsx — no RTL.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { listAreasMock, listProjectsMock, listTodosMock, createAreaMock, updateAreaMock, getFiltersMock } =
  vi.hoisted(() => ({
    listAreasMock: vi.fn(),
    listProjectsMock: vi.fn(),
    listTodosMock: vi.fn(),
    createAreaMock: vi.fn(),
    updateAreaMock: vi.fn(),
    getFiltersMock: vi.fn(),
  }));

vi.mock('./api', () => ({
  listAreas: listAreasMock,
  listProjects: listProjectsMock,
  listTodos: listTodosMock,
  createArea: createAreaMock,
  updateArea: updateAreaMock,
  getFilters: getFiltersMock,
  createTodo: vi.fn(),
  updateTodo: vi.fn(),
  createProject: vi.fn(),
}));

import { AreasPage } from './AreasPage';
import { ApiError } from './errors';
import { resetUndoQueue } from './undoQueue';
import type { Todo, TodoArea, TodoProject } from './types';
import { AREA_EXTRA, ITEM_EXTRA, PROJECT_EXTRA } from './testFixtures';

const AT = '2026-09-01T12:00:00Z';

const area = (id: number, name: string, over: Partial<TodoArea> = {}): TodoArea =>
  ({ ...AREA_EXTRA, id, name, notes: '', status: 'active', created_at: AT, updated_at: AT, ...over });

const project = (id: number, name: string, area_id: number | null): TodoProject =>
  ({ ...PROJECT_EXTRA, id, name, notes: '', status: 'active', open_count: 2, area_id, created_at: AT, updated_at: AT });

const todo = (id: number, title: string, over: Partial<Todo>): Todo => ({ ...ITEM_EXTRA,
  id, title, notes: '', project_id: null, project_name: null, context: '', tags: [],
  status: 'next_action', star: false, due_date: null, repeat: '', auto_star_on_due: false,
  source: 'ui', created_at: AT, updated_at: AT, completed_at: null, ...over,
});

const AREAS = [area(1, 'Health'), area(2, 'Work', { notes: 'the day job' }), area(3, 'Old job', { status: 'dropped' })];
const PROJECTS = [project(10, 'Ship the launch', 2), project(11, 'Run a 10k', 1), project(12, 'Loose project', null)];
const NEXT = [
  // Inherits Work from its project: its OWN area_id is unset.
  todo(100, 'Draft the announcement', { project_id: 10, area_id: null, effective_area_id: 2 }),
  todo(101, 'Book a physio', { area_id: 1, effective_area_id: 1 }),
  // In the Work project, but filed under Health by its own area.
  todo(102, 'Stretch at the desk', { project_id: 10, area_id: 1, effective_area_id: 1 }),
  todo(103, 'No area at all', {}),
];
const SOMEDAY = [
  todo(200, 'Learn to row', { status: 'someday_maybe', area_id: 1, effective_area_id: 1 }),
];

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  listAreasMock.mockReset().mockResolvedValue(AREAS);
  listProjectsMock.mockReset().mockResolvedValue(PROJECTS);
  listTodosMock.mockReset().mockImplementation(({ status }: { status: string }) =>
    Promise.resolve(status === 'next_action' ? NEXT : SOMEDAY));
  createAreaMock.mockReset().mockResolvedValue(area(4, 'Family'));
  updateAreaMock.mockReset().mockResolvedValue(AREAS[0]);
  getFiltersMock.mockReset().mockResolvedValue({ contexts: [], tags: [], status_counts: {} });
  resetUndoQueue();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  resetUndoQueue();
});

async function render() {
  await act(async () => {
    root.render(<MemoryRouter><AreasPage /></MemoryRouter>);
  });
}
const settle = () => act(async () => { await Promise.resolve(); });

const card = (name: string) => container.querySelector<HTMLElement>(`[data-area="${name}"]`)!;
/** The rows under one heading inside an area card: project links, or todo titles. */
function under(name: string, heading: string): string[] {
  const h3 = [...card(name).querySelectorAll('h3')].find(h => h.textContent === heading);
  if (!h3) return [];
  const block = h3.nextElementSibling!;
  return heading === 'Projects'
    ? [...block.querySelectorAll('a')].map(a => a.querySelector('span')!.textContent ?? '')
    : [...block.querySelectorAll('p.text-sm')].map(p => p.textContent ?? '');
}
const button = (scope: ParentNode, text: string) =>
  [...scope.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent?.trim() === text)!;
const nameInput = () => container.querySelector<HTMLInputElement>('input[aria-label="New area name"]')!;
function type(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value')?.set;
  act(() => {
    setter?.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

describe('AreasPage — what each area holds', () => {
  it('asks for active projects, next actions and someday items', async () => {
    await render();
    expect(listProjectsMock).toHaveBeenCalledWith('active');
    expect(listTodosMock.mock.calls.map(c => c[0].status).sort()).toEqual(['next_action', 'someday_maybe']);
  });

  it('lists each active area with its projects, next actions and someday items', async () => {
    await render();
    expect([...container.querySelectorAll('[data-area]')].map(s => s.getAttribute('data-area')))
      .toEqual(['Health', 'Work']);

    expect(under('Work', 'Projects')).toEqual(['Ship the launch']);
    expect(under('Work', 'Next actions')).toEqual(['Draft the announcement']);
    expect(under('Work', 'Someday')).toEqual([]);
    expect(card('Work').textContent).toContain('the day job');

    expect(under('Health', 'Projects')).toEqual(['Run a 10k']);
    expect(under('Health', 'Next actions')).toEqual(['Book a physio', 'Stretch at the desk']);
    expect(under('Health', 'Someday')).toEqual(['Learn to row']);
  });

  it('files a todo under the area it shows under, not the raw column', async () => {
    await render();
    // Inherited from the project (own area unset) — still under Work.
    expect(under('Work', 'Next actions')).toContain('Draft the announcement');
    // Its own area beats its project's.
    expect(under('Work', 'Next actions')).not.toContain('Stretch at the desk');
    // A todo and a project with no area appear under no area.
    expect(container.textContent).not.toContain('No area at all');
    expect(container.textContent).not.toContain('Loose project');
  });

  it('links each project to its detail page', async () => {
    await render();
    expect(card('Work').querySelector('a')!.getAttribute('href')).toBe('/todos/projects/10');
  });

  it('says so when an area has nothing live under it', async () => {
    listAreasMock.mockResolvedValue([area(5, 'Finances')]);
    await render();
    expect(card('Finances').textContent).toContain('Nothing live here yet');
  });

  it('explains what an area is when there are none', async () => {
    listAreasMock.mockResolvedValue([]);
    await render();
    expect(container.textContent).toContain('No areas yet');
  });

  it('offers a retry when the load fails', async () => {
    listAreasMock.mockRejectedValue(new Error('offline'));
    await render();
    expect(container.textContent).toContain("Couldn't load");
  });
});

describe('AreasPage — writes', () => {
  it('adds an area by name and reloads', async () => {
    await render();
    type(nameInput(), '  Family ');
    act(() => button(nameInput().form!, 'Add').click());
    await settle();
    expect(createAreaMock).toHaveBeenCalledWith({ name: 'Family', visibility: 'private' });
    expect(listAreasMock).toHaveBeenCalledTimes(2);
    expect(nameInput().value).toBe('');
  });

  it('shows a refusal and keeps what was typed', async () => {
    createAreaMock.mockRejectedValue(new ApiError(422, 'Area "work" already exists'));
    await render();
    type(nameInput(), 'work');
    act(() => button(nameInput().form!, 'Add').click());
    await settle();
    expect(container.querySelector('[role="alert"]')!.textContent).toBe('Area "work" already exists');
    expect(nameInput().value).toBe('work');
    expect(listAreasMock).toHaveBeenCalledTimes(1);
  });

  it('renames an area in place, writing only the name', async () => {
    await render();
    act(() => card('Work').querySelector<HTMLButtonElement>('button[title="Click to rename"]')!.click());
    const editor = card('Work').querySelector<HTMLTextAreaElement>('textarea[aria-label="Area name"]')!;
    type(editor, 'Career');
    act(() => { editor.dispatchEvent(new FocusEvent('focusout', { bubbles: true })); });
    await settle();
    expect(updateAreaMock).toHaveBeenCalledWith(2, { name: 'Career' });
  });

  it('archives and restores, and offers no delete', async () => {
    await render();
    act(() => button(card('Health'), 'Archive').click());
    await settle();
    expect(updateAreaMock).toHaveBeenLastCalledWith(1, { status: 'dropped' });

    const archived = [...container.querySelectorAll('li')].find(li => li.textContent?.includes('Old job'))!;
    act(() => button(archived, 'Restore').click());
    await settle();
    expect(updateAreaMock).toHaveBeenLastCalledWith(3, { status: 'active' });

    expect([...container.querySelectorAll('button')].some(b => /delete/i.test(b.textContent ?? ''))).toBe(false);
  });
});
