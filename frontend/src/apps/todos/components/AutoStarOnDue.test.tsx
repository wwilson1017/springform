// @vitest-environment jsdom
//
// Issue todo-gtd #1615's client-side half: `auto_star_on_due` is only meaningful for a
// REPEATING todo, so both capture surfaces hide the toggle until a repeat rule
// exists and force the field to false when it does not.
//
// That gating is a silent failure if it breaks. The checkbox keeps its own state,
// so a user who checks it and then clears the repeat rule would otherwise ship a
// todo carrying a hidden auto-star — invisible in the UI (nothing renders it
// without a repeat) right up until they add a repeat rule back and their next
// occurrence stars itself for no reason the user can see.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { createTodoMock, updateTodoMock } = vi.hoisted(() => ({
  createTodoMock: vi.fn(),
  updateTodoMock: vi.fn(),
}));
vi.mock('../api', () => ({
  createTodo: createTodoMock,
  updateTodo: updateTodoMock,
}));

import { QuickAdd } from './QuickAdd';
import { TodoEditSheet } from './TodoEditSheet';
import type { Todo } from '../types';
import { ITEM_EXTRA } from '../testFixtures';
import { routed } from '../testRouter';

const TODO: Todo = { ...ITEM_EXTRA,
  id: 1, title: 'water the plants', notes: '', project_id: null, project_name: null,
  context: '', tags: [], status: 'next_action', star: false, due_date: null,
  repeat: 'weekly', auto_star_on_due: false, source: 'ui',
  created_at: '2026-08-06T12:00:00Z', updated_at: '2026-08-06T12:00:00Z', completed_at: null,
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = routed(createRoot(container));
  createTodoMock.mockReset().mockResolvedValue(TODO);
  updateTodoMock.mockReset().mockResolvedValue(TODO);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

/** React tracks the value it last rendered, so a plain `el.value = x` is invisible
 * to it — go through the prototype setter the way React's own tracker does. */
function setValue(el: HTMLSelectElement | HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value')?.set;
  act(() => {
    setter?.call(el, value);
    el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }));
  });
}

const click = (el: Element) => act(() => { (el as HTMLElement).click(); });

/** The auto-star checkbox, found by its label rather than by position — the
 * star checkbox sits right beside it and index-based lookup would silently
 * follow the wrong one if the order ever changed. */
function autoStarBox(): HTMLInputElement | null {
  const label = [...container.querySelectorAll('label')]
    .find(l => l.textContent?.includes('next occurrence'));
  return label?.querySelector('input[type="checkbox"]') ?? null;
}

function button(label: string): HTMLButtonElement {
  const found = [...container.querySelectorAll('button')]
    .find(b => b.textContent?.trim() === label);
  if (!found) throw new Error(`no button labelled "${label}"`);
  return found;
}

describe('TodoEditSheet auto-star gating', () => {
  const renderSheet = async (todo: Todo) => {
    await act(async () => {
      root.render(
        <TodoEditSheet todo={todo} projects={[]} contexts={[]}
                       onClose={() => {}} onSaved={() => {}} />,
      );
    });
  };

  it('offers the toggle only once a repeat rule is set', async () => {
    await renderSheet({ ...TODO, repeat: '' });
    expect(autoStarBox()).toBeNull();

    setValue(container.querySelector<HTMLSelectElement>('#tgtd-repeat')!, 'weekly');
    expect(autoStarBox()).not.toBeNull();
  });

  it('saves the flag when it is checked against a repeating todo', async () => {
    await renderSheet(TODO);
    click(autoStarBox()!);
    await act(async () => { button('Save').click(); });

    expect(updateTodoMock).toHaveBeenCalledTimes(1);
    expect(updateTodoMock.mock.calls[0][1]).toMatchObject({
      repeat: 'weekly', auto_star_on_due: true,
    });
  });

  it('clears the flag when the repeat rule is removed in the same edit', async () => {
    await renderSheet({ ...TODO, auto_star_on_due: true });
    expect(autoStarBox()!.checked).toBe(true);

    setValue(container.querySelector<HTMLSelectElement>('#tgtd-repeat')!, '');
    await act(async () => { button('Save').click(); });

    expect(updateTodoMock.mock.calls[0][1]).toMatchObject({
      repeat: '', auto_star_on_due: false,
    });
  });
});

describe('QuickAdd auto-star gating', () => {
  const renderQuickAdd = async () => {
    await act(async () => { root.render(<QuickAdd onAdded={() => {}} />); });
  };
  const input = () => container.querySelector<HTMLInputElement>('input:not([type="checkbox"])')!;

  it('offers the toggle only once the parse finds a repeat rule', async () => {
    await renderQuickAdd();
    setValue(input(), 'water the plants');
    expect(autoStarBox()).toBeNull();

    setValue(input(), 'water the plants every week');
    expect(autoStarBox()).not.toBeNull();
  });

  it('sends the flag with a parsed repeating capture', async () => {
    await renderQuickAdd();
    setValue(input(), 'water the plants every week');
    click(autoStarBox()!);
    await act(async () => { button('Add').click(); });

    expect(createTodoMock).toHaveBeenCalledTimes(1);
    expect(createTodoMock.mock.calls[0][0]).toMatchObject({
      repeat: 'weekly', auto_star_on_due: true,
    });
  });

  it('drops a checked flag when the repeat phrase is edited back out', async () => {
    await renderQuickAdd();
    setValue(input(), 'water the plants every week');
    click(autoStarBox()!);
    setValue(input(), 'water the plants');
    await act(async () => { button('Add').click(); });

    expect(createTodoMock.mock.calls[0][0]).toMatchObject({
      repeat: '', auto_star_on_due: false,
    });
  });
});
