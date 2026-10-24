// @vitest-environment jsdom
//
// #2352: the sheet's Context field was an <input list>/<datalist>. Mobile browsers do
// not reliably render a datalist on a POPULATED text input, so there was no picker at
// all until the field was cleared — and what surfaced then was the OS autofill bar,
// not app UI. It is now the <select>-plus-escape-hatch shape TriageCard already uses
// and that Status/Project/Repeat use in this very form.
//
// None of the properties that change is about are visible to tsc or eslint: that the
// option VALUES are indices (so a context named like the sentinel stays selectable),
// that the meta list arrives asynchronously (an index frozen at mount would then point
// at the wrong context), and that what save() writes is still the context STRING.
//
// createRoot + React 19 act, following TriageCard.test.tsx — no RTL.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

const { updateTodoMock } = vi.hoisted(() => ({ updateTodoMock: vi.fn() }));
vi.mock('../api', () => ({
  createTodo: vi.fn(),
  updateTodo: updateTodoMock,
}));

import { TodoEditSheet } from './TodoEditSheet';
import type { Todo } from '../types';
import { ITEM_EXTRA } from '../testFixtures';
import { routed } from '../testRouter';

const TODO: Todo = { ...ITEM_EXTRA,
  id: 7,
  title: 'Call the plumber',
  notes: '',
  project_id: null,
  project_name: null,
  context: '@calls',
  tags: [],
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

let container: HTMLDivElement;
let root: Root;
let onSaved: Mock<() => void>;
let onClose: Mock<() => void>;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = routed(createRoot(container));
  updateTodoMock.mockReset().mockResolvedValue(TODO);
  onSaved = vi.fn();
  onClose = vi.fn();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function render(todo: Partial<Todo> | null = {}, contexts = ['@calls', '@errands']) {
  act(() => {
    root.render(
      <TodoEditSheet
        todo={todo === null ? null : { ...TODO, ...todo }}
        projects={[]}
        contexts={contexts}
        onClose={onClose}
        onSaved={onSaved}
      />,
    );
  });
}

/** React tracks the value it last rendered, so a plain `el.value = x` is invisible
 * to it — go through the prototype setter the way React's own tracker does. */
function setValue(el: HTMLSelectElement | HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value')?.set;
  act(() => {
    setter?.call(el, value);
    el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }));
  });
}

const picker = () => container.querySelector<HTMLSelectElement>('#tgtd-context')!;
const newContextInput = () =>
  container.querySelector<HTMLInputElement>('input[aria-label="New context"]');
const labels = () => [...picker().options].map(o => o.textContent);

async function save() {
  const btn = [...container.querySelectorAll('button')].find(b => b.textContent?.trim() === 'Save')!;
  act(() => { btn.click(); });
  await act(async () => {});
  return updateTodoMock.mock.calls.at(-1)?.[1] as Record<string, unknown>;
}

describe('the context field is a real picker, not a datalist (#2352)', () => {
  it('is a <select> and leaves no datalist behind', () => {
    render();
    expect(picker().tagName).toBe('SELECT');
    // The negative form matters: the bug was that the datalist rendered nothing
    // usable on mobile, so a leftover one would put the old control back.
    expect(container.querySelector('datalist')).toBeNull();
    expect(container.querySelector('input[list]')).toBeNull();
  });

  it('offers the known contexts, "no context", and an escape hatch', () => {
    render();
    expect(labels()).toEqual(['No context', '@calls', '@errands', '+ New context…']);
  });

  it('preselects the context the todo already has', () => {
    render({ context: '@errands' });
    expect(picker().selectedOptions[0].textContent).toBe('@errands');
  });

  it('offers a context the shared meta has not caught up with', () => {
    // Quick Add can mint a context, and the meta list is fetched separately — without
    // this the picker would read "No context" for a todo that plainly has one.
    render({ context: '@garage' }, ['@calls']);
    expect(labels()).toEqual(['No context', '@garage', '@calls', '+ New context…']);
    expect(picker().selectedOptions[0].textContent).toBe('@garage');
  });

  it('keeps pointing at the same context when the meta list arrives late', () => {
    // First paint has an empty meta list, so the todo's own context is the only option.
    // An index frozen at mount would still say "0" once the real list lands — and "0"
    // is then a DIFFERENT context, silently reassigning the todo on the next save.
    render({ context: '@errands' }, []);
    expect(picker().selectedOptions[0].textContent).toBe('@errands');

    render({ context: '@errands' }, ['@calls', '@errands']);
    expect(picker().selectedOptions[0].textContent).toBe('@errands');
  });

  it('keeps the picked context selected when a metadata refresh drops it', async () => {
    // `contexts` is a shared module-level cache that any mounted component can refresh, so
    // the list can lose a value while this sheet is open. An option list built only from the
    // todo's ORIGINAL context would then match nothing — the select would read "No context"
    // while `save()` still submitted the hidden string.
    render({ context: '@calls' }, ['@calls', '@errands']);
    setValue(picker(), '1'); // '@errands'

    render({ context: '@calls' }, ['@calls']); // the refresh no longer lists it

    expect(picker().selectedOptions[0].textContent).toBe('@errands');
    expect(await save()).toMatchObject({ context: '@errands' });
  });

  it('saves the picked context as a string', async () => {
    render();
    setValue(picker(), '1'); // '@errands'
    expect(await save()).toMatchObject({ context: '@errands' });
  });

  it('saves an empty context when "No context" is picked', async () => {
    render();
    setValue(picker(), '');
    expect(await save()).toMatchObject({ context: '' });
  });

  it('can still select a context whose name collides with the sentinel', () => {
    // Why the option values are indices rather than the context strings, exactly as
    // TriageCard documents: with string values this option would BE the sentinel and
    // picking it would open the create-a-new-one input instead of selecting it.
    render({ context: '' }, ['__new__']);
    setValue(picker(), '0');
    expect(newContextInput()).toBeNull();
    expect(picker().selectedOptions[0].textContent).toBe('__new__');
  });
});

describe('creating a context from the sheet', () => {
  it('reveals an input and saves what is typed into it', async () => {
    render();
    expect(newContextInput()).toBeNull();

    setValue(picker(), '__new__');
    const input = newContextInput()!;
    expect(input).toBeTruthy();
    setValue(input, ' @garage ');

    expect(await save()).toMatchObject({ context: '@garage' });
  });

  it('goes back to the picker — with the picked value — when an existing one is chosen instead', async () => {
    render();
    setValue(picker(), '__new__');
    setValue(newContextInput()!, '@half-typed');

    setValue(picker(), '0'); // '@calls'
    expect(newContextInput()).toBeNull();
    expect(await save()).toMatchObject({ context: '@calls' });
  });

  it('is where a brand-new todo starts, with nothing preselected', () => {
    render(null);
    expect(picker().value).toBe('');
    expect(picker().selectedOptions[0].textContent).toBe('No context');
  });
});
