// @vitest-environment jsdom
//
// The people input, on the two surfaces that carry it.
//
// What tsc cannot see: that people the list already knows are OFFERED (and that one
// already on the todo is not offered twice), that typing narrows the offer and a click
// replaces the half-typed fragment rather than appending after it, that a name nobody
// has used yet is simply accepted, and that what reaches the server is the list of
// names — once, as `people`, never folded into `tags`. On the triage card the field
// has no Save button, so the write itself is the behaviour: at once on a pick, on blur
// for typed text, and not at all when nothing changed.
//
// createRoot + React 19 act, following TodoEditSheet.context.test.tsx — no RTL.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { updateTodoMock, createTodoMock } = vi.hoisted(() => ({
  updateTodoMock: vi.fn(),
  createTodoMock: vi.fn(),
}));
vi.mock('../api', () => ({
  createTodo: createTodoMock,
  updateTodo: updateTodoMock,
  createProject: vi.fn(),
}));
// The sheet and the card read people and areas from the shared meta cache, which a
// page's shell fills. Here it is simply given.
vi.mock('../useTodoMeta', () => ({
  useListFilters: () => ({
    contexts: ['@calls'], tags: [], status_counts: {},
    people: ['Ana', 'Bo', 'Bob'],
    areas: [{ id: 4, name: 'Work' }],
  }),
}));

import { TodoEditSheet } from './TodoEditSheet';
import { TriageCard } from './TriageCard';
import type { Todo, TodoProject } from '../types';
import { ITEM_EXTRA, PROJECT_EXTRA } from '../testFixtures';
import { routed } from '../testRouter';

const TODO: Todo = { ...ITEM_EXTRA,
  id: 7,
  title: 'Ask about the lease',
  notes: '',
  project_id: null,
  project_name: null,
  context: '@calls',
  tags: ['home'],
  people: ['Bo'],
  status: 'next_action',
  star: false,
  due_date: null,
  repeat: '',
  auto_star_on_due: false,
  source: 'ui',
  created_at: '2026-08-06T12:00:00Z',
  updated_at: '2026-08-06T12:00:00Z',
  completed_at: null,
};

const PROJECT: TodoProject = { ...PROJECT_EXTRA,
  id: 3, name: 'Move house', notes: '', status: 'active', open_count: 1,
  area_id: 4, area_name: 'Work',
  created_at: '2026-08-06T12:00:00Z', updated_at: '2026-08-06T12:00:00Z',
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = routed(createRoot(container));
  updateTodoMock.mockReset().mockResolvedValue(TODO);
  createTodoMock.mockReset().mockResolvedValue(TODO);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function setValue(el: HTMLSelectElement | HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value')?.set;
  act(() => {
    setter?.call(el, value);
    el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }));
  });
}

const offered = () =>
  [...container.querySelectorAll('[data-people-suggestions] button')].map(b => b.textContent);
const offer = (name: string) =>
  [...container.querySelectorAll<HTMLButtonElement>('[data-people-suggestions] button')]
    .find(b => b.textContent === `+ ${name}`)!;
const settle = () => act(async () => {});

describe('the people field in the edit sheet', () => {
  function renderSheet(todo: Partial<Todo> | null = {}) {
    act(() => {
      root.render(
        <TodoEditSheet
          todo={todo === null ? null : { ...TODO, ...todo }}
          projects={[PROJECT]}
          contexts={['@calls']}
          onClose={() => {}}
          onSaved={() => {}}
        />,
      );
    });
  }
  const input = () => container.querySelector<HTMLInputElement>('#tgtd-people')!;
  async function save(label = 'Save') {
    const btn = [...container.querySelectorAll('button')].find(b => b.textContent?.trim() === label)!;
    act(() => { btn.click(); });
    await settle();
  }

  it('shows who is on the todo and offers only the people who are not', () => {
    renderSheet();
    expect(input().value).toBe('Bo');
    // "Bo" is a finished entry, not a search: it must not hide everyone but "Bob".
    expect(offered()).toEqual(['+ Ana', '+ Bob']);
    act(() => offer('Ana').click());
    expect(input().value).toBe('Bo, Ana'); // joined on, not swapped for "Bo"
    expect(offered()).toEqual(['+ Bob']);
  });

  it('narrows as you type, and a click replaces the fragment being typed', () => {
    renderSheet({ people: [] });
    expect(offered()).toEqual(['+ Ana', '+ Bo', '+ Bob']);
    setValue(input(), 'Zed, an');
    expect(offered()).toEqual(['+ Ana']);
    act(() => offer('Ana').click());
    expect(input().value).toBe('Zed, Ana');
    expect(offered()).toEqual(['+ Bo', '+ Bob']);
  });

  it('accepts a brand new person and saves the names as `people`, apart from tags', async () => {
    renderSheet();
    setValue(input(), ' Bo ,, Zed ');
    await save();
    const fields = updateTodoMock.mock.calls.at(-1)?.[1] as Record<string, unknown>;
    expect(updateTodoMock.mock.calls.at(-1)?.[0]).toBe(7);
    expect(fields.people).toEqual(['Bo', 'Zed']);
    expect(fields.tags).toEqual(['home']);
  });

  it('emptying the field clears the people', async () => {
    renderSheet();
    setValue(input(), '');
    await save();
    expect((updateTodoMock.mock.calls.at(-1)?.[1] as Record<string, unknown>).people).toEqual([]);
  });

  it('creates a todo with its people', async () => {
    renderSheet(null);
    setValue(container.querySelector<HTMLInputElement>('#tgtd-title')!, 'Lunch');
    act(() => offer('Ana').click());
    await save('Add');
    expect(createTodoMock.mock.calls.at(-1)?.[0]).toMatchObject({ title: 'Lunch', people: ['Ana'] });
  });
});

describe('the bring-back date and the area picker in the edit sheet', () => {
  function renderSheet(todo: Partial<Todo> = {}) {
    act(() => {
      root.render(
        <TodoEditSheet todo={{ ...TODO, ...todo }} projects={[PROJECT]} contexts={[]}
                       onClose={() => {}} onSaved={() => {}} />,
      );
    });
  }
  const revisit = () => container.querySelector<HTMLInputElement>('#tgtd-revisit');
  const area = () => container.querySelector<HTMLSelectElement>('#tgtd-area')!;
  async function saved() {
    const btn = [...container.querySelectorAll('button')].find(b => b.textContent?.trim() === 'Save')!;
    act(() => { btn.click(); });
    await settle();
    return updateTodoMock.mock.calls.at(-1)?.[1] as Record<string, unknown>;
  }

  it('offers "Bring back on…" once the item is someday, as a native date input', async () => {
    renderSheet();
    expect(revisit()).toBeNull();
    setValue(container.querySelector<HTMLSelectElement>('#tgtd-status')!, 'someday_maybe');
    expect(revisit()!.type).toBe('date');
    setValue(revisit()!, '2026-10-04');
    expect(await saved()).toMatchObject({ status: 'someday_maybe', revisit_on: '2026-10-04' });
  });

  it('keeps a date that is already set visible on any status, and a save does not drop it', async () => {
    renderSheet({ revisit_on: '2026-10-04' });
    expect(revisit()!.value).toBe('2026-10-04');
    expect((await saved()).revisit_on).toBe('2026-10-04');
  });

  it('clears the date when the field is emptied', async () => {
    renderSheet({ status: 'someday_maybe', revisit_on: '2026-10-04' });
    setValue(revisit()!, '');
    expect((await saved()).revisit_on).toBeNull();
  });

  const inProject = { project_id: 3, project_name: 'Move house', effective_area_id: 4, area_name: 'Work' };

  it('says when the todo is inheriting its project\'s area, and a save does not pin it', async () => {
    renderSheet(inProject);
    expect(area().value).toBe('');
    expect(area().options[0].textContent).toBe('Same as project (Work)');
    expect((await saved()).area_id).toBeNull();
  });

  it('writes the todo\'s OWN area when one is picked', async () => {
    renderSheet(inProject);
    setValue(area(), '4');
    expect((await saved()).area_id).toBe(4);
  });

  it('keeps an option for an area that has since been archived', () => {
    renderSheet({ area_id: 9, effective_area_id: 9, area_name: 'Old job' });
    expect(area().value).toBe('9');
    expect([...area().options].map(o => o.textContent)).toEqual(['No area', 'Old job', 'Work']);
  });
});

describe('the people field on the triage card', () => {
  let onChanged: ReturnType<typeof vi.fn<() => void>>;
  let onEdit: ReturnType<typeof vi.fn<(t: Todo) => void>>;

  function renderCard(todo: Partial<Todo> = {}) {
    onChanged = vi.fn();
    onEdit = vi.fn();
    act(() => {
      root.render(
        <TriageCard todo={{ ...TODO, status: 'inbox', context: '', people: [], ...todo }}
                    projects={[]} contexts={[]} onProcessed={() => {}}
                    onChanged={onChanged} onEdit={onEdit} />,
      );
    });
  }
  const input = () => container.querySelector<HTMLInputElement>('input[aria-label="People"]')!;
  const blur = () => act(() => { input().dispatchEvent(new FocusEvent('focusout', { bubbles: true })); });

  it('writes at once when a known person is picked, and leaves the item in the inbox', async () => {
    renderCard();
    act(() => offer('Ana').click());
    await settle();
    expect(updateTodoMock).toHaveBeenCalledTimes(1);
    expect(updateTodoMock).toHaveBeenCalledWith(7, { people: ['Ana'] });
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it('writes a typed new person on blur', async () => {
    renderCard({ people: ['Bo'] });
    setValue(input(), 'Bo, Zed');
    expect(updateTodoMock).not.toHaveBeenCalled();
    blur();
    await settle();
    expect(updateTodoMock).toHaveBeenCalledWith(7, { people: ['Bo', 'Zed'] });
  });

  it('writes nothing when the field is left unchanged', async () => {
    renderCard({ people: ['Bo'] });
    setValue(input(), ' Bo ');
    blur();
    await settle();
    expect(updateTodoMock).not.toHaveBeenCalled();
  });

  it('hands the full editor the people as typed, not the stale saved list', async () => {
    renderCard({ people: ['Bo'] });
    setValue(input(), 'Bo, Zed');
    const edit = [...container.querySelectorAll('button')].find(b => b.textContent === 'Edit')!;
    act(() => { edit.click(); });
    await settle();
    expect(onEdit.mock.calls.at(-1)?.[0].people).toEqual(['Bo', 'Zed']);
  });

  it('says so when the write is refused', async () => {
    updateTodoMock.mockRejectedValue(new Error('too many people (max 50)'));
    renderCard();
    act(() => offer('Bo').click());
    await settle();
    expect(container.textContent).toContain('too many people (max 50)');
    expect(onChanged).not.toHaveBeenCalled();
  });
});
