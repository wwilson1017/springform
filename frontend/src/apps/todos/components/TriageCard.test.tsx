// @vitest-environment jsdom
//
// Issue #1548 rebuilt the inbox triage card as Chatty's 3-step clarify flow, and every
// property that change is ABOUT is invisible to tsc and eslint: that a destination button
// no longer writes anything, that setting a context is the only exit from the inbox, that
// "Done ✓" and "Drop" are the two deliberate exceptions, and that a filed card cannot be
// used a second time while the parent's reload is still in flight. Those get executable
// proofs — a screenshot cannot tell "the card stayed put" from "the write silently failed".
//
// createRoot + React 19 act, following SearchableSelect.test.tsx — no RTL.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

const { updateTodoMock, createProjectMock, updateProjectMock } = vi.hoisted(() => ({
  updateTodoMock: vi.fn(),
  createProjectMock: vi.fn(),
  updateProjectMock: vi.fn(),
}));
vi.mock('../api', () => ({
  updateTodo: updateTodoMock,
  createProject: createProjectMock,
  updateProject: updateProjectMock,
}));

import { TriageCard } from './TriageCard';
import { toast } from '../toast';
import { resetUndoQueue, takeAll } from '../undoQueue';
import type { Todo, TodoProject } from '../types';
import { ITEM_EXTRA, PROJECT_EXTRA } from '../testFixtures';

const TODO: Todo = { ...ITEM_EXTRA,
  id: 7,
  title: 'dentist',
  notes: '',
  project_id: null,
  project_name: null,
  context: '',
  tags: [],
  status: 'inbox',
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
let onProcessed: Mock<() => void>;
let onChanged: Mock<() => void>;
let onEdit: Mock<(t: Todo) => void>;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  updateTodoMock.mockReset().mockResolvedValue(TODO);
  createProjectMock.mockReset().mockResolvedValue({ ...PROJECT, id: 9, name: 'Garage' });
  updateProjectMock.mockReset().mockResolvedValue(PROJECT);
  onProcessed = vi.fn();
  onChanged = vi.fn();
  onEdit = vi.fn();
  resetUndoQueue();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
  vi.restoreAllMocks(); // the toast spies are per-test — don't leak them
});

const PROJECT: TodoProject = { ...PROJECT_EXTRA,
  id: 3, name: 'Kitchen remodel', notes: '', status: 'active', open_count: 2,
  created_at: '2026-08-06T12:00:00Z', updated_at: '2026-08-06T12:00:00Z',
};

function render(todo: Partial<Todo> = {}, contexts = ['@calls', '@errands'], projects = [PROJECT]) {
  act(() => {
    root.render(
      <TriageCard
        todo={{ ...TODO, ...todo }}
        projects={projects}
        contexts={contexts}
        onProcessed={onProcessed}
        onChanged={onChanged}
        onEdit={onEdit}
      />,
    );
  });
}

/** React tracks the value it last rendered, so a plain `el.value = x` is invisible
 * to it — go through the prototype setter the way React's own tracker does. */
function setValue(el: HTMLSelectElement | HTMLTextAreaElement | HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value')?.set;
  act(() => {
    setter?.call(el, value);
    el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }));
  });
}

function click(el: Element) {
  act(() => { (el as HTMLElement).click(); });
}

function button(label: string): HTMLButtonElement {
  const found = [...container.querySelectorAll('button')].find(
    b => (b.textContent ?? '').trim() === label,
  );
  if (!found) throw new Error(`no button labelled "${label}"`);
  return found;
}

const contextPicker = () =>
  container.querySelector<HTMLSelectElement>('select[aria-label="Set context and file this todo"]')!;

const projectPicker = () =>
  container.querySelector<HTMLSelectElement>('select[aria-label="Project"]');

const projectNameInput = () =>
  container.querySelector<HTMLInputElement>('input[aria-label="New project name"]');

const submitForm = (el: Element) => {
  act(() => {
    el.closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
};

describe('step 1 — choosing a destination', () => {
  it('writes nothing and keeps the card on screen', () => {
    render();
    click(button('Waiting'));

    expect(updateTodoMock).not.toHaveBeenCalled();
    expect(onProcessed).not.toHaveBeenCalled();
    expect(onChanged).not.toHaveBeenCalled();
    expect(button('Waiting').getAttribute('aria-pressed')).toBe('true');
  });

  it('is carried into the single filing write', async () => {
    render();
    click(button('Waiting'));
    setValue(contextPicker(), '0'); // '@calls'
    await act(async () => {});

    expect(updateTodoMock).toHaveBeenCalledTimes(1);
    expect(updateTodoMock).toHaveBeenCalledWith(7, { context: '@calls', status: 'waiting_for' });
    expect(onProcessed).toHaveBeenCalledTimes(1);
  });

  it('defaults to next_action when left alone', async () => {
    render();
    setValue(contextPicker(), '1'); // '@errands'
    await act(async () => {});

    expect(updateTodoMock).toHaveBeenCalledWith(7, { context: '@errands', status: 'next_action' });
  });
});

describe('step 3 — context is the only exit', () => {
  it('offers no skip option — every choice but "new" is a context', () => {
    render();
    const values = [...contextPicker().options].map(o => o.textContent);
    expect(values).toEqual(['Set context…', '@calls', '@errands', '+ New context…']);
  });

  it('writes nothing when the placeholder is re-selected', async () => {
    render();
    setValue(contextPicker(), '');
    await act(async () => {});

    expect(updateTodoMock).not.toHaveBeenCalled();
    expect(onProcessed).not.toHaveBeenCalled();
  });

  it('writes nothing when a blank new context is submitted', async () => {
    render();
    setValue(contextPicker(), 'new');
    const input = container.querySelector<HTMLInputElement>('input[aria-label="New context"]')!;
    setValue(input, '   ');
    act(() => { input.closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
    await act(async () => {});

    expect(updateTodoMock).not.toHaveBeenCalled();
    expect(onProcessed).not.toHaveBeenCalled();
  });

  it('files under a newly typed context', async () => {
    render();
    setValue(contextPicker(), 'new');
    const input = container.querySelector<HTMLInputElement>('input[aria-label="New context"]')!;
    setValue(input, ' @garage ');
    act(() => { input.closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
    await act(async () => {});

    expect(updateTodoMock).toHaveBeenCalledWith(7, { context: '@garage', status: 'next_action' });
    expect(onProcessed).toHaveBeenCalledTimes(1);
  });

  it("offers the item's own context even when the shared meta is empty", () => {
    render({ context: '@home' }, []);
    expect([...contextPicker().options].map(o => o.textContent))
      .toEqual(['Set context…', '@home', '+ New context…']);
  });
});

describe('tags typed just before filing', () => {
  it('are saved before the filing write is sent', async () => {
    let answer!: (v: unknown) => void;
    updateTodoMock.mockImplementationOnce(() => new Promise(r => { answer = r; }));
    render();
    const tags = container.querySelector<HTMLInputElement>('input[aria-label="Tags"]')!;
    setValue(tags, 'errand');
    act(() => { tags.dispatchEvent(new FocusEvent('focusout', { bubbles: true })); });
    setValue(contextPicker(), '0');
    await act(async () => {});
    expect(updateTodoMock).toHaveBeenCalledTimes(1); // the filing write is waiting
    await act(async () => { answer(TODO); });
    expect(updateTodoMock.mock.calls.map(c => c[1])).toEqual([
      { tags: ['errand'] }, { context: '@calls', status: 'next_action' },
    ]);
  });
});

describe('step 2 — every field says what it is', () => {
  it('labels project, due date, notes, tags and people', () => {
    render();
    const shown = [...container.querySelectorAll('span')].map(e => e.textContent);
    for (const name of ['Project', 'Due date', 'Notes', 'Tags', 'People']) expect(shown).toContain(name);
  });
});

describe('the resolves contract — in-place edits must not advance the card', () => {
  // patch(fields, resolves) decides between onChanged and onProcessed on a bare
  // boolean, and every one of these call sites is one flipped literal away from
  // filing an item the user only meant to annotate. The card would advance to
  // the next todo mid-clarify and the edited one would leave the inbox with
  // whatever status happened to be selected.
  it.each([
    ['star', () => click(button('★')), { star: true }],
    ['project', () => setValue(container.querySelector<HTMLSelectElement>('select[aria-label="Project"]')!, '3'), { project_id: 3 }],
    ['due date', () => {
      const due = container.querySelector<HTMLInputElement>('input[aria-label="Due date"]')!;
      setValue(due, '2026-09-01');
      act(() => { due.dispatchEvent(new FocusEvent('focusout', { bubbles: true })); }); // written on blur
    }, { due_date: '2026-09-01' }],
    ['tags', () => {
      const tags = container.querySelector<HTMLInputElement>('input[aria-label="Tags"]')!;
      setValue(tags, 'errand, 5 min');
      act(() => { tags.dispatchEvent(new FocusEvent('focusout', { bubbles: true })); }); // written on blur
    }, { tags: ['errand', '5 min'] }],
  ])('%s writes in place and stays on the card', async (_label, act_, payload) => {
    render();
    act_();
    await act(async () => {});

    expect(updateTodoMock).toHaveBeenCalledWith(7, payload);
    expect(onChanged).toHaveBeenCalledTimes(1);
    expect(onProcessed).not.toHaveBeenCalled();
  });
});

describe('the two exceptions — done and delete need no context', () => {
  it('completes immediately', async () => {
    render();
    click(button('Took 2 minutes — Done ✓'));
    await act(async () => {});

    expect(updateTodoMock).toHaveBeenCalledWith(7, { status: 'done' });
    expect(onProcessed).toHaveBeenCalledTimes(1);
  });

  it('has no Delete: Drop archives the todo and leaves the inbox', async () => {
    // Nothing is ever deleted. Drop is a resolving write to status 'dropped'.
    render();
    expect(() => button('Delete')).toThrow();
    click(button('Drop'));
    await act(async () => {});

    expect(updateTodoMock).toHaveBeenCalledWith(7, { status: 'dropped' });
    expect(onProcessed).toHaveBeenCalledTimes(1);
  });

  it('labels a todo Whisk or an AI tool created "AI"', () => {
    render({ source: 'agent' });
    expect(container.textContent).toContain('Added by AI');
  });

  it('shows no provenance label on a todo a person added', () => {
    render({ source: 'ui' });
    expect(container.textContent).not.toContain('Added by');
  });
});

describe('a resolved card is spent', () => {
  // The parent reloads asynchronously and keeps rendering this todo until the new
  // list lands. Re-enabling the controls in that window let a second write hit an
  // item that had already left the inbox — picking a context right after "Done ✓"
  // would reopen a completed (and by then already re-spawned) repeating todo.
  it('cannot be filed again after being completed', async () => {
    render();
    click(button('Took 2 minutes — Done ✓'));
    await act(async () => {});
    updateTodoMock.mockClear();

    setValue(contextPicker(), '0');
    await act(async () => {});

    expect(updateTodoMock).not.toHaveBeenCalled();
    expect(onProcessed).toHaveBeenCalledTimes(1);
  });

  it('stays usable when the write fails', async () => {
    updateTodoMock.mockRejectedValueOnce(new Error('nope'));
    render();
    setValue(contextPicker(), '0');
    await act(async () => {});

    expect(onProcessed).not.toHaveBeenCalled();
    expect(container.textContent).toContain('nope');

    updateTodoMock.mockResolvedValue(TODO);
    setValue(contextPicker(), '0');
    await act(async () => {});
    expect(onProcessed).toHaveBeenCalledTimes(1);
  });
});

describe('step 2 — creating a project without leaving triage', () => {
  // Two writes behind one gesture (POST /projects, then PUT /todos/{id}), and the
  // state BETWEEN them is the whole risk: the project outlives a failed assignment,
  // so "creating failed" would send the user back to make a duplicate — which the
  // unique-name constraint then rejects, stranding them.
  const openCreate = () => {
    setValue(projectPicker()!, 'new');
    return projectNameInput()!;
  };

  it('offers the create option below the real projects', () => {
    render();
    expect([...projectPicker()!.options].map(o => o.textContent))
      .toEqual(['No project', 'Kitchen remodel', '+ New project…']);
  });

  it('creates the project and files this item under it, in place', async () => {
    render();
    const input = openCreate();
    expect(projectPicker()).toBeNull(); // the picker is swapped out while creating
    setValue(input, '  Garage  ');
    submitForm(input);
    await act(async () => {});

    expect(createProjectMock).toHaveBeenCalledWith({ name: 'Garage', area_id: null, purpose: '', outcome: '', visibility: 'private' });
    expect(updateTodoMock).toHaveBeenCalledWith(7, { project_id: 9 });
    // Non-resolving: same tier as the other step-2 fields, so the card stays put.
    expect(onChanged).toHaveBeenCalledTimes(1);
    expect(onProcessed).not.toHaveBeenCalled();
    expect(projectPicker()).toBeTruthy(); // back to the dropdown
  });

  it('refuses a whitespace-only name', async () => {
    render();
    const input = openCreate();
    setValue(input, '   ');
    submitForm(input);
    await act(async () => {});

    expect(createProjectMock).not.toHaveBeenCalled();
    expect(updateTodoMock).not.toHaveBeenCalled();
  });

  it('cancels back to the picker with the previous project untouched', () => {
    render({ project_id: 3 });
    openCreate();
    click(button('Cancel'));

    expect(createProjectMock).not.toHaveBeenCalled();
    expect(updateTodoMock).not.toHaveBeenCalled();
    expect(projectPicker()!.value).toBe('3');
  });

  it('keeps the name input open when the project could not be created', async () => {
    // A duplicate name is the common rejection, and it is fixable right there —
    // dropping back to the dropdown would discard what they typed.
    createProjectMock.mockRejectedValueOnce(new Error('Project "Garage" already exists'));
    render();
    const input = openCreate();
    setValue(input, 'Garage');
    submitForm(input);
    await act(async () => {});

    expect(updateTodoMock).not.toHaveBeenCalled();
    expect(projectNameInput()!.value).toBe('Garage');
    expect(container.textContent).toContain('already exists');

    // …and correcting the name in that same field works.
    setValue(projectNameInput()!, 'Garage shelving');
    submitForm(projectNameInput()!);
    await act(async () => {});

    expect(createProjectMock).toHaveBeenLastCalledWith({ name: 'Garage shelving', area_id: null, purpose: '', outcome: '', visibility: 'private' });
    expect(updateTodoMock).toHaveBeenCalledWith(7, { project_id: 9 });
    expect(projectPicker()).toBeTruthy();
  });

  it('clears the failed-create message when the attempt is abandoned', async () => {
    // The message belongs to the attempt being cancelled; left up, it reads as a
    // failure of whatever the user does next.
    createProjectMock.mockRejectedValueOnce(new Error('Project "Garage" already exists'));
    render();
    const input = openCreate();
    setValue(input, 'Garage');
    submitForm(input);
    await act(async () => {});
    expect(container.textContent).toContain('already exists');

    click(button('Cancel'));
    expect(container.textContent).not.toContain('already exists');
  });

  it('says the project WAS created when only the assignment fails — as a toast', async () => {
    // A TOAST, not this card's inline error. Promoting another queue row is not
    // gated on `busy`, so the head item can change while these two writes are in
    // flight; InboxPage keys the card by todo id, so this card unmounts and an
    // inline setError would land on a dead component and be lost. That is the one
    // message that must never go quiet — the project exists either way.
    const toastError = vi.spyOn(toast, 'error');
    updateTodoMock.mockRejectedValueOnce(new Error('offline'));
    render();
    const input = openCreate();
    setValue(input, 'Garage');
    submitForm(input);
    await act(async () => {});

    expect(createProjectMock).toHaveBeenCalledTimes(1);
    expect(toastError).toHaveBeenCalledTimes(1);
    expect(toastError.mock.calls[0][0]).toContain('Created “Garage”');
    // The recovery the message promises must actually exist: onChanged is what
    // reloads the project list, so re-render the way the parent would and prove
    // the new project is selectable. Asserting only that "a picker is showing"
    // would pass with the project absent — the affordance is the point.
    expect(onChanged).toHaveBeenCalledTimes(1);
    const GARAGE: TodoProject = { ...PROJECT, id: 9, name: 'Garage' };
    render({}, ['@calls', '@errands'], [PROJECT, GARAGE]);
    expect([...projectPicker()!.options].map(o => o.textContent))
      .toEqual(['No project', 'Kitchen remodel', 'Garage', '+ New project…']);
  });

  it('locks the form while the two writes are in flight, so one gesture cannot create twice', async () => {
    // The guard is `if (busy || !value) return` plus `disabled={busy}` on the
    // input and submit. Without it a double-submit (Enter held, an impatient
    // second click) races a second POST, and the unique-name constraint turns
    // the loser into a confusing "already exists" on a name the user only
    // entered once.
    // BOTH writes are deferred: releasing only the POST would let the PUT resolve
    // in the same tick, and a regression that cleared `busy` between the two
    // would sail through unnoticed.
    let releasePost!: (p: TodoProject) => void;
    let releasePut!: (t: Todo) => void;
    createProjectMock.mockImplementationOnce(() => new Promise<TodoProject>(r => { releasePost = r; }));
    updateTodoMock.mockImplementationOnce(() => new Promise<Todo>(r => { releasePut = r; }));
    render();
    const input = openCreate();
    setValue(input, 'Garage');
    submitForm(input);
    await act(async () => {});

    // Write 1 in flight — the form is locked.
    expect(createProjectMock).toHaveBeenCalledTimes(1);
    expect(projectNameInput()!.disabled).toBe(true);
    expect(button('Create').disabled).toBe(true);

    submitForm(projectNameInput()!); // a second gesture while in flight
    await act(async () => {});
    expect(createProjectMock).toHaveBeenCalledTimes(1);

    // Write 2 in flight — the form has closed back to the picker, which must
    // stay disabled until the assignment settles.
    await act(async () => { releasePost({ ...PROJECT, id: 9, name: 'Garage' }); });
    expect(updateTodoMock).toHaveBeenCalledWith(7, { project_id: 9 });
    expect(projectPicker()!.disabled).toBe(true);

    await act(async () => { releasePut(TODO); });
    expect(projectPicker()!.disabled).toBe(false);
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it('still assigns an existing project the ordinary way', async () => {
    render();
    setValue(projectPicker()!, '3');
    await act(async () => {});

    expect(createProjectMock).not.toHaveBeenCalled();
    expect(updateTodoMock).toHaveBeenCalledWith(7, { project_id: 3 });
  });
});

describe('inline title editing', () => {
  const openEditor = () => {
    click(button('dentist'));
    return container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Todo title"]')!;
  };

  const press = (el: Element, key: string) => {
    act(() => { el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true })); });
  };

  const blur = (el: Element) => {
    act(() => { el.dispatchEvent(new FocusEvent('focusout', { bubbles: true })); });
  };

  it('saves a trimmed title on Enter without filing the item', async () => {
    render();
    const editor = openEditor();
    setValue(editor, '  call the dentist to book a cleaning  ');
    press(editor, 'Enter');
    await act(async () => {});

    expect(updateTodoMock).toHaveBeenCalledWith(7, { title: 'call the dentist to book a cleaning' });
    expect(onChanged).toHaveBeenCalledTimes(1);
    expect(onProcessed).not.toHaveBeenCalled();
  });

  it('saves on blur', async () => {
    render();
    const editor = openEditor();
    setValue(editor, 'renamed');
    blur(editor);
    await act(async () => {});

    expect(updateTodoMock).toHaveBeenCalledWith(7, { title: 'renamed' });
  });

  it('rejects a whitespace-only title instead of saving a blank one', async () => {
    render();
    const editor = openEditor();
    setValue(editor, '   ');
    press(editor, 'Enter');
    await act(async () => {});

    expect(updateTodoMock).not.toHaveBeenCalled();
    expect(button('dentist')).toBeTruthy();
  });

  it('reverts on Escape', async () => {
    render();
    const editor = openEditor();
    setValue(editor, 'something else');
    press(editor, 'Escape');
    await act(async () => {});

    expect(updateTodoMock).not.toHaveBeenCalled();
    expect(button('dentist')).toBeTruthy();
  });

  it('keeps the editor open with the typed text when the save fails', async () => {
    // Closing on failure reverts to the old title and silently discards the
    // rename the user just typed — and rewriting a vague capture IS the point
    // of the card, so that text is the work, not a keystroke.
    updateTodoMock.mockRejectedValueOnce(new Error('offline'));
    render();
    const editor = openEditor();
    setValue(editor, 'call the dentist');
    press(editor, 'Enter');
    await act(async () => {});

    const stillOpen = container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Todo title"]');
    expect(stillOpen).toBeTruthy();
    expect(stillOpen!.value).toBe('call the dentist');
    expect(container.textContent).toContain('offline');

    // …and retrying from that same editor works.
    updateTodoMock.mockResolvedValue(TODO);
    press(stillOpen!, 'Enter');
    await act(async () => {});
    expect(updateTodoMock).toHaveBeenLastCalledWith(7, { title: 'call the dentist' });
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it('locks the editor while the save is in flight, so two title writes cannot overlap', async () => {
    // The title save deliberately does NOT take the card-wide `busy` flag (a
    // shared flag would swallow the very click that blurred the editor), so
    // keeping the editor itself disabled is the only thing preventing a second,
    // stale rename from racing the first.
    let release!: (t: Todo) => void;
    updateTodoMock.mockImplementationOnce(() => new Promise<Todo>(r => { release = r; }));
    render();
    const editor = openEditor();
    setValue(editor, 'call the dentist');
    press(editor, 'Enter');
    await act(async () => {});

    const inFlight = container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Todo title"]')!;
    expect(inFlight.disabled).toBe(true);
    expect(updateTodoMock).toHaveBeenCalledTimes(1);

    await act(async () => { release({ ...TODO, title: 'call the dentist' }); });
    expect(updateTodoMock).toHaveBeenCalledTimes(1);
  });

  it('hands the Edit sheet the renamed title, not the stale prop', async () => {
    // Clicking Edit is what blurs the editor, so one gesture both STARTS the
    // rename and opens the sheet. TodoEditSheet snapshots the title it is given
    // and writes it back on its next full-field save — so passing the stale
    // prop here silently reverts the rename the user just made.
    render();
    const editor = openEditor();
    setValue(editor, 'call the dentist');
    // jsdom's .click() does not move focus, so drive the real order by hand:
    // the browser blurs the editor on mousedown, then dispatches the click.
    blur(editor);
    click(button('Edit'));
    await act(async () => {});

    expect(onEdit).toHaveBeenCalledTimes(1);
    expect(onEdit.mock.calls[0][0].title).toBe('call the dentist');
  });

  it('names the undo row by the renamed title, not the stale prop', async () => {
    // The same lag as the Edit sheet above: until the parent's refetch lands the
    // `todo` prop still carries the old title, and an item filed or finished in that
    // window used to offer its undo under the name the user had just replaced.
    updateTodoMock.mockResolvedValueOnce(
      { ...TODO, title: 'call the dentist', updated_at: '2026-08-06T12:05:00Z', rev: 6 });
    render();
    const editor = openEditor();
    setValue(editor, 'call the dentist');
    blur(editor);
    await act(async () => {}); // the rename is saved; the prop still says "dentist"

    click(button('Took 2 minutes — Done ✓'));
    await act(async () => {});

    const queued = takeAll();
    expect(queued.map(e => e.title)).toEqual(['call the dentist']);
    expect(queued[0].restore).toEqual({ status: 'inbox' }); // what undo puts back is unchanged
  });

  it('never names the undo row by a rename the server refused', async () => {
    // Clicking Done is what blurs the editor, so the rename and the completion go out
    // in one gesture. If the rename is refused (too long, say) while the completion
    // lands, the card is gone and the undo row is the only thing left on screen: it
    // must carry the title that is actually stored.
    updateTodoMock.mockRejectedValueOnce(new Error('Title too long'));
    render();
    const editor = openEditor();
    setValue(editor, 'a title the server will refuse');
    blur(editor);
    click(button('Took 2 minutes — Done ✓'));
    await act(async () => {});

    expect(updateTodoMock).toHaveBeenCalledWith(7, { status: 'done' });
    expect(takeAll().map(e => e.title)).toEqual(['dentist']);
  });

  it('names the undo row by a same-gesture rename that the server then saves', async () => {
    // Clicking Done blurs the editor, so the rename is still in flight when the
    // completion starts. The completion waits for it, and the undo row carries the
    // title the server stored rather than the one the card held at the click.
    let release!: (t: Todo) => void;
    updateTodoMock.mockImplementationOnce(() => new Promise<Todo>(r => { release = r; }));
    render();
    const editor = openEditor();
    setValue(editor, 'call the dentist');
    blur(editor);
    click(button('Took 2 minutes — Done ✓'));
    await act(async () => {});
    expect(updateTodoMock).not.toHaveBeenCalledWith(7, { status: 'done' }); // waits for the rename

    await act(async () => {
      release({ ...TODO, title: 'call the dentist', updated_at: '2026-08-06T12:05:00Z', rev: 6 });
    });

    expect(updateTodoMock).toHaveBeenLastCalledWith(7, { status: 'done' });
    expect(takeAll().map(e => e.title)).toEqual(['call the dentist']);
  });

  it('keeps a saved rename whose version ties the one the card already holds', async () => {
    // A rename can answer with the same `rev` as a row the card already adopted (its own
    // write's echo). The tie must not discard the rename.
    let release!: (t: Todo) => void;
    updateTodoMock.mockImplementationOnce(() => new Promise<Todo>(r => { release = r; }));
    render();
    const editor = openEditor();
    setValue(editor, 'call the dentist');
    blur(editor);
    click(button('Took 2 minutes — Done ✓'));
    await act(async () => { release({ ...TODO, title: 'call the dentist' }); }); // same rev

    expect(takeAll().map(e => e.title)).toEqual(['call the dentist']);
  });

  it('prefers a newer title from elsewhere over this card\'s earlier rename', async () => {
    // The last rename's answer is kept for the card's life; a refetch carrying a later
    // edit (another device, an agent) is the newer stored title and must win.
    updateTodoMock.mockResolvedValueOnce(
      { ...TODO, title: 'call the dentist', updated_at: '2026-08-06T12:05:00Z', rev: 6 });
    render();
    const editor = openEditor();
    setValue(editor, 'call the dentist');
    blur(editor);
    await act(async () => {});
    render({ title: 'book the dentist for March', updated_at: '2026-08-06T12:10:00Z', rev: 11 });

    click(button('Took 2 minutes — Done ✓'));
    await act(async () => {});

    expect(takeAll().map(e => e.title)).toEqual(['book the dentist for March']);
  });

  it('does not hand the sheet a rename that failed to save', async () => {
    updateTodoMock.mockRejectedValueOnce(new Error('offline'));
    render();
    const editor = openEditor();
    setValue(editor, 'never persisted');
    press(editor, 'Enter');
    await act(async () => {});

    // The editor stayed open with the text (retryable); the user gives up.
    press(container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Todo title"]')!, 'Escape');
    await act(async () => {});
    click(button('Edit'));
    await act(async () => {}); // Edit flushes the notes chain before it opens the sheet

    expect(onEdit.mock.calls[0][0].title).toBe('dentist');
  });

  it('stops masking the title once the row moves on', async () => {
    // `pendingTitle` used to be cleared only on failure, so after ONE in-card rename it
    // masked every later rename from the Edit sheet or another client — and the sheet, handed
    // `current`, wrote the old title back on its next save. Pre-existing (#1548-era); the
    // due-date override added here states the rule it was breaking.
    render();
    const editor = openEditor();
    setValue(editor, 'renamed here');
    press(editor, 'Enter');
    await act(async () => {});

    render({ title: 'renamed in the sheet', updated_at: '2026-08-06T12:05:00Z', rev: 6 });

    expect(button('renamed in the sheet')).toBeTruthy();
    click(button('Edit'));
    await act(async () => {});
    expect(onEdit.mock.calls.at(-1)![0].title).toBe('renamed in the sheet');
  });

  it('ignores the refetch fired by an earlier rename', async () => {
    // Rename to A, then to B before A's refetch returns. That refetch carries A and a
    // timestamp newer than the MOUNT, so without recording the version each rename produced
    // it clears `pendingTitle` and restores A — and the Edit sheet then writes A back over B.
    const openTitle = (label: string) => {
      click(button(label));
      return container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Todo title"]')!;
    };
    updateTodoMock.mockResolvedValueOnce({ ...TODO, title: 'A', updated_at: '2026-08-06T12:05:00Z', rev: 6 });
    render();
    let ed = openTitle('dentist');
    setValue(ed, 'A');
    press(ed, 'Enter');
    await act(async () => {});

    updateTodoMock.mockResolvedValueOnce({ ...TODO, title: 'B', updated_at: '2026-08-06T12:09:00Z', rev: 10 });
    ed = openTitle('A');
    setValue(ed, 'B');
    press(ed, 'Enter');
    await act(async () => {});

    render({ title: 'A', updated_at: '2026-08-06T12:05:00Z', rev: 6 }); // the first rename's refetch

    expect(button('B')).toBeTruthy();
  });

  it('does not re-save on the blur that follows Enter', async () => {
    render();
    const editor = openEditor();
    setValue(editor, 'renamed');
    press(editor, 'Enter');
    blur(editor);
    await act(async () => {});

    expect(updateTodoMock).toHaveBeenCalledTimes(1);
  });
});

describe('step 2 — the due-date cue (#2351)', () => {
  // A native <input type="date"> ignores `placeholder` and renders the browser's own
  // mm/dd/yyyy instead, so "Add due date" is an overlay. Nothing in tsc or eslint can
  // see whether that overlay is present, absent once a date exists, or — the one that
  // actually breaks the control — still sitting on top of the native editor while the
  // user is picking a date.
  const dueInput = () =>
    container.querySelector<HTMLInputElement>('input[aria-label="Due date"]')!;
  const cue = () =>
    [...container.querySelectorAll('span[aria-hidden="true"]')]
      .find(el => (el.textContent ?? '').trim() === 'Add due date');
  const focus = (el: Element) => {
    act(() => { el.dispatchEvent(new FocusEvent('focusin', { bubbles: true })); });
  };
  const unfocus = (el: Element) => {
    act(() => { el.dispatchEvent(new FocusEvent('focusout', { bubbles: true })); });
  };

  it('labels the empty box in place of the missing placeholder', () => {
    render();
    expect(cue()).toBeTruthy();
  });

  it('goes away once the todo has a due date', () => {
    render({ due_date: '2026-09-01' });
    expect(cue()).toBeUndefined();
    expect(dueInput().value).toBe('2026-09-01');
  });

  it('uncovers the native editor while the field has focus', () => {
    render();
    focus(dueInput());
    expect(cue()).toBeUndefined();
    unfocus(dueInput());
    expect(cue()).toBeTruthy();
  });

  it('comes back after the date is cleared', async () => {
    render();
    focus(dueInput());
    setValue(dueInput(), '2026-09-01');
    unfocus(dueInput());
    await act(async () => {});
    render({ due_date: '2026-09-01', updated_at: '2026-08-06T12:05:00Z', rev: 6 });
    expect(cue()).toBeUndefined();

    focus(dueInput());
    setValue(dueInput(), '');
    unfocus(dueInput());
    await act(async () => {});
    render({ due_date: null, updated_at: '2026-08-06T12:09:00Z', rev: 10 });

    expect(updateTodoMock).toHaveBeenLastCalledWith(7, { due_date: null });
    expect(dueInput().value).toBe('');
    expect(cue()).toBeTruthy();
  });

  it('survives a date typed a keystroke at a time into an empty box', async () => {
    // The exact sequence a date input emits: it reports a COMPLETE value as soon as every
    // segment parses, so typing "12242026" arrives as four values, one per year digit.
    // Writing the first set `busy`, which disabled the input, and the remaining keystrokes
    // went nowhere — `0002-12-24` is what reached the server.
    render();
    setValue(dueInput(), '0002-12-24');
    setValue(dueInput(), '0020-12-24');
    setValue(dueInput(), '0202-12-24');
    setValue(dueInput(), '2026-12-24');
    unfocus(dueInput());
    await act(async () => {});

    expect(updateTodoMock.mock.calls).toEqual([[7, { due_date: '2026-12-24' }]]);
  });

  it('survives a date typed over one the todo already had', async () => {
    // The commoner gesture: with a date already set, the FIRST keystroke completes a
    // parseable value (`2026-01-01` after the month's "1"), so the truncation landed on the
    // very first key and stored a wrong date rather than none.
    render({ due_date: '2026-10-01' });
    setValue(dueInput(), '2026-01-01');
    setValue(dueInput(), '2026-12-01');
    setValue(dueInput(), '2026-12-02');
    setValue(dueInput(), '2026-12-24');
    unfocus(dueInput());
    await act(async () => {});

    expect(updateTodoMock.mock.calls).toEqual([[7, { due_date: '2026-12-24' }]]);
  });

  it('is inert to the pointer, so tapping it still opens the picker', () => {
    render();
    expect(cue()!.className).toContain('pointer-events-none');
  });

  it('keeps the picked date on screen until the reload lands', async () => {
    // The input is CONTROLLED by `todo.due_date`, so between the write being sent and the
    // parent's refetch arriving the field would otherwise blank out — taking the date the
    // user just chose with it and bringing the cue back on top.
    render();
    focus(dueInput());
    setValue(dueInput(), '2026-09-01');
    unfocus(dueInput());
    await act(async () => {}); // the PUT settled; the parent has NOT re-rendered this card

    expect(dueInput().value).toBe('2026-09-01');
    expect(cue()).toBeUndefined();
  });

  it('drops the optimistic date when the write fails', async () => {
    // Same rule as `pendingTitle`: nothing was written, so the field must not go on
    // showing a date the server never took.
    const toastError = vi.spyOn(toast, 'error').mockImplementation(() => {});
    updateTodoMock.mockRejectedValueOnce(new Error('offline'));
    render();
    setValue(dueInput(), '2026-09-01');
    unfocus(dueInput());
    await act(async () => {});

    expect(dueInput().value).toBe('');
    expect(cue()).toBeTruthy();
    expect(container.textContent).toContain('offline');
    // A toast as well: the blur that commits can be the click that swaps this card away.
    expect(toastError).toHaveBeenCalledTimes(1);
  });

  it('hands the Edit sheet the date on screen, not the stale prop', async () => {
    // Same trap as the title and the notes: during the write-to-refetch gap the prop still
    // holds the OLD date, and the sheet writes back every field it was handed.
    render();
    setValue(dueInput(), '2026-09-01');
    await act(async () => {});
    click(button('Edit'));
    await act(async () => {});

    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ due_date: '2026-09-01' }));
  });

  it('keeps notes typed while the date write was still in flight', async () => {
    // The card stays editable during the date write, and the save's continuation belongs to
    // the render that started it — where the notes box was still clean. Adopting the answer
    // from there would read the box as untouched and put the server's old notes back over
    // what was typed since.
    let land!: (t: Todo) => void;
    updateTodoMock.mockReturnValueOnce(new Promise<Todo>(r => { land = r; }));
    render();
    setValue(dueInput(), '2026-09-01');
    unfocus(dueInput()); // the date write is in flight
    const notes = container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Notes"]')!;
    setValue(notes, 'typed meanwhile');

    await act(async () => {
      land({ ...TODO, due_date: '2026-09-01', updated_at: '2026-08-06T12:05:00Z', rev: 6 });
    });

    expect(notes.value).toBe('typed meanwhile');
    expect(dueInput().value).toBe('2026-09-01');
  });

  it('waits for the date write before opening the Edit sheet', async () => {
    // Clicking Edit is what blurs the field, and the sheet writes `due_date` too — so the
    // card's own PUT has to answer first, or it can land after the sheet's and overwrite it.
    let land!: (t: Todo) => void;
    updateTodoMock.mockReturnValueOnce(new Promise<Todo>(r => { land = r; }));
    render();
    setValue(dueInput(), '2026-09-01');
    unfocus(dueInput());
    click(button('Edit'));
    await act(async () => {});
    expect(onEdit).not.toHaveBeenCalled(); // the write is still in flight

    await act(async () => {
      land({ ...TODO, due_date: '2026-09-01', updated_at: '2026-08-06T12:05:00Z', rev: 6 });
    });
    expect(updateTodoMock).toHaveBeenCalledTimes(1);
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ due_date: '2026-09-01' }));
  });

  it('locks the card while Edit waits on its writes', async () => {
    // Only the Edit button used to be disabled during that wait, so a star or project change
    // made in it started a write the sheet never saw: the sheet opened on the old value, and
    // its full-field save put it back.
    let land!: (t: Todo) => void;
    updateTodoMock.mockReturnValueOnce(new Promise<Todo>(r => { land = r; }));
    render();
    setValue(dueInput(), '2026-09-01');
    unfocus(dueInput());
    click(button('Edit')); // waits on the date write
    expect(button('★').disabled).toBe(true);
    click(button('★'));
    expect(updateTodoMock).toHaveBeenCalledTimes(1); // the date write, and no other

    await act(async () => {
      land({ ...TODO, due_date: '2026-09-01', updated_at: '2026-08-06T12:05:00Z', rev: 6 });
    });
    expect(onEdit).toHaveBeenCalledTimes(1);
    expect(button('★').disabled).toBe(false);
  });

  it('hands the Edit sheet what was typed while it waited on the date write', async () => {
    // The card is locked during that wait (the test above), but its writes still answer into
    // it, and the sheet writes back every field it is handed. It must get the card as it is
    // when it opens, not as it was at the click. Typed straight into the DOM here, past the
    // lock, to stand for any change that lands in the wait.
    let land!: (t: Todo) => void;
    updateTodoMock.mockReturnValueOnce(new Promise<Todo>(r => { land = r; }));
    render();
    setValue(dueInput(), '2026-09-01');
    unfocus(dueInput());
    click(button('Edit')); // waits on the date write
    setValue(container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Notes"]')!,
      'typed while waiting');

    await act(async () => {
      land({ ...TODO, due_date: '2026-09-01', updated_at: '2026-08-06T12:05:00Z', rev: 6 });
    });
    expect(onEdit).toHaveBeenCalledWith(
      expect.objectContaining({ notes: 'typed while waiting', due_date: '2026-09-01' }));
  });

  it('lets a newer row keep its date when this write answers late', async () => {
    // Another client moved the date after this write committed, and the reload carrying
    // that row landed first. The late answer is rightly ignored as stale — and must not
    // then put its own date back under the newer row's version, where no later reload
    // could ever correct it.
    let land!: (t: Todo) => void;
    updateTodoMock.mockReturnValueOnce(new Promise<Todo>(r => { land = r; }));
    render();
    setValue(dueInput(), '2026-09-01');
    unfocus(dueInput());
    render({ due_date: '2026-09-20', updated_at: '2026-08-06T12:09:00Z', rev: 10 });

    await act(async () => {
      land({ ...TODO, due_date: '2026-09-01', updated_at: '2026-08-06T12:05:00Z', rev: 6 });
    });
    expect(dueInput().value).toBe('2026-09-20');
  });

  it('keeps the date when an older write of this card answers after it', async () => {
    // The date is written on blur and no longer takes the card-wide busy flag, so the click
    // that blurs it can start a second write alongside. If the server commits that one FIRST
    // and it answers LAST, its row is the older of the two — and has the date from before.
    let landDate!: (t: Todo) => void;
    let landStar!: (t: Todo) => void;
    updateTodoMock
      .mockReturnValueOnce(new Promise<Todo>(r => { landDate = r; }))
      .mockReturnValueOnce(new Promise<Todo>(r => { landStar = r; }));
    render();
    setValue(dueInput(), '2026-09-01');
    unfocus(dueInput());
    click(button('★'));

    await act(async () => {
      landDate({ ...TODO, star: true, due_date: '2026-09-01', updated_at: '2026-08-06T12:09:00Z', rev: 10 });
    });
    await act(async () => {
      landStar({ ...TODO, star: true, updated_at: '2026-08-06T12:05:00Z', rev: 6 });
    });

    expect(dueInput().value).toBe('2026-09-01');
  });

  it('gives way to a different date the reload brings back', async () => {
    // An override that only cleared on an exact match would mask an authoritative value the
    // card never wrote — the Edit sheet changing it, another client, or server canonicalising.
    render();
    setValue(dueInput(), '2026-09-01');
    unfocus(dueInput());
    await act(async () => {});
    expect(dueInput().value).toBe('2026-09-01');

    render({ due_date: '2026-09-05', updated_at: '2026-08-06T12:05:00Z', rev: 6 });
    expect(dueInput().value).toBe('2026-09-05');
  });

  it('writes nothing for a date typed back to what it was, and does not pin it', async () => {
    render({ due_date: '2026-09-01' });
    setValue(dueInput(), '2026-09-02');
    setValue(dueInput(), '2026-09-01');
    unfocus(dueInput());
    await act(async () => {});
    expect(updateTodoMock).not.toHaveBeenCalled();

    render({ due_date: '2026-09-05', updated_at: '2026-08-06T12:05:00Z', rev: 6 }); // the sheet moved it
    expect(dueInput().value).toBe('2026-09-05');
  });

  it('never discards a half-typed date when a reload lands', () => {
    // The same rule as the notes: the parent reloads after every in-place edit, and a newer
    // row is not a reason to wipe what the user is in the middle of typing.
    render();
    setValue(dueInput(), '0002-12-24');
    render({ notes: 'saved a moment ago', updated_at: '2026-08-06T12:05:00Z', rev: 6 });

    expect(dueInput().value).toBe('0002-12-24');
  });

  it('sends a date retyped during the first write as ONE trailing write', async () => {
    // Two overlapping PUTs to one column land in whichever order the server picks, and the
    // first write answering must not release the newer date still in the box.
    let land!: (t: Todo) => void;
    updateTodoMock.mockReturnValueOnce(new Promise<Todo>(r => { land = r; }));
    // The trailing write answers the way the server does, with a newer `rev`: an
    // answer OLDER than the row the card holds is one it rightly sets aside.
    updateTodoMock.mockResolvedValueOnce({
      ...TODO, due_date: '2026-09-10', updated_at: '2026-08-06T12:09:00Z', rev: 10,
    });
    render();
    setValue(dueInput(), '2026-09-01');
    unfocus(dueInput());
    setValue(dueInput(), '2026-09-10');
    unfocus(dueInput()); // a second commit while the first write is still in flight
    expect(updateTodoMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      land({ ...TODO, due_date: '2026-09-01', updated_at: '2026-08-06T12:05:00Z', rev: 6 });
    });

    expect(updateTodoMock.mock.calls.map(c => c[1])).toEqual(
      [{ due_date: '2026-09-01' }, { due_date: '2026-09-10' }]);
    expect(dueInput().value).toBe('2026-09-10');
  });

  it.each([
    ['after the blur that a real click causes', true],
    ['with the field still focused', false],
  ])('carries a date just picked into the write that files the item (%s)', async (_label, blurs) => {
    // The click that files the item is what blurs the field, so the commit and the filing
    // write are one gesture — and a resolving write flushes the date first, once.
    render();
    setValue(dueInput(), '2026-12-24');
    if (blurs) unfocus(dueInput());
    setValue(contextPicker(), '0'); // '@calls'
    await act(async () => {});

    expect(updateTodoMock.mock.calls).toEqual([
      [7, { due_date: '2026-12-24' }],
      [7, { context: '@calls', status: 'next_action' }],
    ]);
  });

  it('ignores the refetch fired by an earlier write when the date has moved on', async () => {
    // The counterpart of the notes echo test, and the reason `patch()` keeps the PUT's
    // response. Pick a date, then pick another before the FIRST write's refetch lands: that
    // refetch carries the first date, which is neither the value on screen nor the one the
    // card last acknowledged. Only a row version taken from each write's own answer can
    // reject it — otherwise the field reverts to the date the user just replaced, and
    // `current` hands that stale date to the Edit sheet, whose save writes back every field.
    updateTodoMock.mockResolvedValueOnce({
      ...TODO, due_date: '2026-09-01', updated_at: '2026-08-06T12:05:00Z', rev: 6,
    });
    render(); // mounted at 12:00, no due date
    setValue(dueInput(), '2026-09-01');
    unfocus(dueInput());
    await act(async () => {});

    updateTodoMock.mockResolvedValueOnce({
      ...TODO, due_date: '2026-09-10', updated_at: '2026-08-06T12:09:00Z', rev: 10,
    });
    setValue(dueInput(), '2026-09-10');
    unfocus(dueInput());
    await act(async () => {});

    // …and now the refetch dispatched back at 12:05 finally lands.
    render({ due_date: '2026-09-01', updated_at: '2026-08-06T12:05:00Z', rev: 6 });

    expect(dueInput().value).toBe('2026-09-10');
    click(button('Edit'));
    await act(async () => {});
    expect(onEdit.mock.calls.at(-1)![0].due_date).toBe('2026-09-10');
  });

  it('does not flash back over a date that was just picked', async () => {
    // The date is written on blur, so `dueFocused` goes false while `todo.due_date` is
    // still the stale prop. Nothing else stops the cue reappearing on top of the chosen
    // date for the length of the round trip.
    let land!: (t: Todo) => void;
    updateTodoMock.mockReturnValueOnce(new Promise<Todo>(r => { land = r; }));
    render();
    focus(dueInput());
    setValue(dueInput(), '2026-09-01');
    unfocus(dueInput());

    expect(cue()).toBeUndefined();
    await act(async () => { land({ ...TODO, due_date: '2026-09-01' }); });
  });
});

describe('step 2 — notes without leaving triage (#2402)', () => {
  const notesBox = () =>
    container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Notes"]')!;
  const unfocus = (el: Element) => {
    act(() => { el.dispatchEvent(new FocusEvent('focusout', { bubbles: true })); });
  };

  it('seeds from the todo and saves on blur without filing the item', async () => {
    render({ notes: 'old' });
    expect(notesBox().value).toBe('old');
    setValue(notesBox(), 'ring 615-555-0100 first');
    unfocus(notesBox());
    await act(async () => {});

    expect(updateTodoMock).toHaveBeenCalledWith(7, { notes: 'ring 615-555-0100 first' });
    expect(onChanged).toHaveBeenCalledTimes(1);
    expect(onProcessed).not.toHaveBeenCalled();
  });

  it('writes nothing when the notes were never touched', async () => {
    render({ notes: 'unchanged' });
    unfocus(notesBox());
    await act(async () => {});

    expect(updateTodoMock).not.toHaveBeenCalled();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it('writes nothing when the notes are typed back to what they were', async () => {
    // The blur handler cannot just ask "was anything typed?" — an edit and its undo
    // leave a draft that is equal to the saved text, and writing it costs a round trip
    // and a full parent reload for nothing.
    render({ notes: 'as filed' });
    setValue(notesBox(), 'as filed and then some');
    setValue(notesBox(), 'as filed');
    unfocus(notesBox());
    await act(async () => {});

    expect(updateTodoMock).not.toHaveBeenCalled();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it('does not take the card-wide busy flag — the blur must not swallow the next click', async () => {
    // Clicking a button is what blurs this textarea. If the notes write went through
    // patch()'s `busy`, the very click that caused the blur would be dropped and the
    // user would have to press the button twice.
    render();
    setValue(notesBox(), 'two minute job');
    unfocus(notesBox());
    click(button('Took 2 minutes — Done ✓'));
    await act(async () => {});

    expect(updateTodoMock).toHaveBeenCalledWith(7, { notes: 'two minute job' });
    expect(updateTodoMock).toHaveBeenCalledWith(7, { status: 'done' });
    expect(onProcessed).toHaveBeenCalledTimes(1);
  });

  it('keeps the typed notes, and hands them to the Edit sheet, when the save fails', async () => {
    // A paragraph of notes is the work, not a keystroke — unlike a failed title save,
    // which reverts, this one must leave the text where the user can still rescue it.
    updateTodoMock.mockRejectedValueOnce(new Error('offline'));
    render();
    setValue(notesBox(), 'the part number is 44-B');
    unfocus(notesBox());
    await act(async () => {});

    expect(container.textContent).toContain('offline');
    expect(notesBox().value).toBe('the part number is 44-B');

    click(button('Edit'));
    await act(async () => {});
    expect(onEdit).toHaveBeenCalledWith(
      expect.objectContaining({ notes: 'the part number is 44-B' }),
    );
  });

  it('adopts notes the Edit sheet wrote — a same-id reload does not remount this card', () => {
    // The sheet writes notes too, and InboxPage keys this card by todo id, so saving
    // the sheet re-renders THIS card with new props instead of mounting a fresh one.
    // A box that only seeded itself once would go on showing the old text — and write
    // it back over the sheet's edit on the next blur.
    render({ notes: 'first' });
    render({ notes: 'written in the sheet', updated_at: '2026-08-06T12:05:00Z', rev: 6 });

    expect(notesBox().value).toBe('written in the sheet');
  });

  it('does not write the pre-sheet text back after adopting the sheet\'s edit', async () => {
    // The hazard the test above NAMES but does not exercise. Adoption is only half the job,
    // and it fails two different ways: if the baseline moves on while the box keeps the old
    // text, the next blur writes that stale text straight over the sheet's edit; and if
    // neither moves, the box still shows the pre-sheet text and the first thing the user
    // types is built on it, overwriting the sheet's edit just the same.
    render({ notes: 'first' });
    render({ notes: 'written in the sheet', updated_at: '2026-08-06T12:05:00Z', rev: 6 });
    updateTodoMock.mockClear();

    unfocus(notesBox()); // untouched: there is nothing to save, so nothing may be written
    await act(async () => {});
    expect(updateTodoMock).not.toHaveBeenCalled();

    // …and what the user types next builds on what they can SEE, which is the whole point.
    setValue(notesBox(), `${notesBox().value}, and mine`);
    unfocus(notesBox());
    await act(async () => {});

    expect(updateTodoMock).toHaveBeenCalledWith(7, { notes: 'written in the sheet, and mine' });
    const wrote = updateTodoMock.mock.calls.map(c => (c[1] as { notes?: string }).notes);
    expect(wrote).not.toContain('first');           // never the pre-sheet text
    expect(wrote).not.toContain('first, and mine'); // nor anything built on it
  });

  it('never discards unsaved notes when a reload lands', () => {
    // The parent reloads after every in-place edit (star, project, due date). Whatever
    // is typed here and not yet saved has to outlive that.
    render({ notes: 'server copy' });
    setValue(notesBox(), 'half a thoug');
    render({ notes: 'changed elsewhere', updated_at: '2026-08-06T12:05:00Z', rev: 6 });

    expect(notesBox().value).toBe('half a thoug');
  });

  it('knows its notes are still unsaved when a newer row arrived before its own answer', async () => {
    // Another client changed the notes after this save committed, and that row reached the
    // card first. The late answer is rightly set aside as stale — and must not then file the
    // text it carried under the newer row's version: the card would believe the server holds
    // it, and no reload could say otherwise. The typed text stays in the box, unsaved, and
    // the next blur sends it.
    let land!: (t: Todo) => void;
    updateTodoMock.mockReturnValueOnce(new Promise<Todo>(r => { land = r; }));
    render({ notes: '' });
    setValue(notesBox(), 'mine');
    unfocus(notesBox());
    render({ notes: 'theirs', updated_at: '2026-08-06T12:09:00Z', rev: 10 });

    await act(async () => {
      land({ ...TODO, notes: 'mine', updated_at: '2026-08-06T12:05:00Z', rev: 6 });
    });
    expect(notesBox().value).toBe('mine');

    unfocus(notesBox());
    await act(async () => {});
    expect(updateTodoMock.mock.calls).toEqual([[7, { notes: 'mine' }], [7, { notes: 'mine' }]]);
  });

  it('follows the server again once the write lands', async () => {
    // The mirror image of the test above: an override that outlived its own save would
    // pin the box to stale text forever, and a later outside edit would never show.
    render({ notes: '' });
    setValue(notesBox(), 'mine');
    unfocus(notesBox());
    await act(async () => {});

    render({ notes: 'sheet wrote this', updated_at: '2026-08-06T12:05:00Z', rev: 6 });
    expect(notesBox().value).toBe('sheet wrote this');
  });

  it('keeps keystrokes typed while the save was still in flight', async () => {
    let land!: (t: Todo) => void;
    updateTodoMock.mockReturnValueOnce(new Promise<Todo>(r => { land = r; }));
    render({ notes: '' });
    setValue(notesBox(), 'first pass');
    unfocus(notesBox());
    setValue(notesBox(), 'first pass, plus more'); // typed again before the write returned

    await act(async () => { land({ ...TODO, notes: 'first pass' }); });

    expect(notesBox().value).toBe('first pass, plus more');
  });

  it('coalesces a second blur into ONE trailing write instead of racing the first', async () => {
    // Two overlapping PUTs to the same column have no defined commit order, so the older
    // text can land last and silently win. The blur-commit primitive answers a commit made
    // during a save with a single trailing run whose payload is recomputed at send time.
    let land!: (t: Todo) => void;
    updateTodoMock.mockReturnValueOnce(new Promise<Todo>(r => { land = r; }));
    render({ notes: '' });
    setValue(notesBox(), 'first pass');
    unfocus(notesBox());
    setValue(notesBox(), 'first pass, plus more');
    unfocus(notesBox()); // a second commit while the first write is still in flight

    expect(updateTodoMock).toHaveBeenCalledTimes(1); // NOT two concurrent writes

    await act(async () => { land({ ...TODO, notes: 'first pass' }); });

    expect(updateTodoMock).toHaveBeenCalledTimes(2);
    expect(updateTodoMock).toHaveBeenLastCalledWith(7, { notes: 'first pass, plus more' });
  });

  it('toasts a failed save, because this card can unmount before the message is read', async () => {
    // A resolving click swaps the head item and InboxPage keys the card by todo id, so the
    // inline error can land on a dead component — exactly the case createAndAssign toasts for.
    const toastError = vi.spyOn(toast, 'error');
    updateTodoMock.mockRejectedValueOnce(new Error('offline'));
    render();
    setValue(notesBox(), 'the part number is 44-B');
    unfocus(notesBox());
    await act(async () => {});

    expect(toastError).toHaveBeenCalledTimes(1);
    expect(toastError.mock.calls[0][0]).toContain('offline');
  });

  it('keeps the saved text on screen while the reload is still in flight', async () => {
    // The baseline moves at save time, so after a successful write the baseline and the
    // prop disagree for the length of the refetch. Adoption that keyed off that difference
    // would read the card's OWN write as an outside edit and revert the box to the text
    // the user just replaced — and the Edit sheet would then be handed the stale copy.
    render({ notes: 'old' });
    setValue(notesBox(), 'new text');
    unfocus(notesBox());
    await act(async () => {});

    expect(notesBox().value).toBe('new text');
    click(button('Edit'));
    await act(async () => {});
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ notes: 'new text' }));
  });

  it('sends a notes edit queued behind an in-flight save before the card resolves', async () => {
    // A resolving write unmounts this card, and an abandoned auto-save chain drops its
    // trailing run — so the queued text has to be flushed BEFORE the filing write, not
    // left to a chain that is about to be thrown away.
    let land!: (t: Todo) => void;
    updateTodoMock.mockReturnValueOnce(new Promise<Todo>(r => { land = r; }));
    render({ notes: '' });
    setValue(notesBox(), 'first');
    unfocus(notesBox());                       // save #1 in flight
    setValue(notesBox(), 'first and second');
    unfocus(notesBox());                       // queued behind it — what clicking a button does
    click(button('Took 2 minutes — Done ✓'));

    await act(async () => { land({ ...TODO, notes: 'first' }); });
    await act(async () => {});

    const sent = updateTodoMock.mock.calls.map(c => c[1] as Record<string, unknown>);
    const queued = sent.findIndex(f => f.notes === 'first and second');
    const filed = sent.findIndex(f => f.status === 'done');
    expect(queued).toBeGreaterThanOrEqual(0);   // it was sent at all
    expect(filed).toBeGreaterThan(queued);      // …and before the card could go away
    expect(onProcessed).toHaveBeenCalledTimes(1);
  });

  it('ignores a refetch older than the write it has already acknowledged', async () => {
    // A save chain dispatches one refetch per run, so two can be in flight and land out of
    // order. The older response carries the pre-trailing text; adopting it would rewind the
    // box — and the next blur would then write the rewound text back over the newer one.
    // Only the row's own `rev` can tell that echo from a real outside edit.
    updateTodoMock.mockResolvedValue({ ...TODO, notes: 'newer', updated_at: '2026-08-06T12:09:00Z', rev: 10 });
    render({ notes: '' });
    setValue(notesBox(), 'newer');
    unfocus(notesBox());
    await act(async () => {});

    // …and now the refetch fired by an EARLIER write finally lands.
    render({ notes: 'older', updated_at: '2026-08-06T12:03:00Z', rev: 4 });

    expect(notesBox().value).toBe('newer');
  });

  it('flushes the notes chain before opening the Edit sheet', async () => {
    // The sheet writes `notes` too. Clicking Edit is what blurs the textarea, so without the
    // flush the card's own PUT is still in flight when the sheet opens — and can land after
    // the sheet's save and overwrite it.
    render({ notes: '' });
    setValue(notesBox(), 'typed on the card');
    click(button('Edit'));
    await act(async () => {});

    expect(updateTodoMock).toHaveBeenCalledWith(7, { notes: 'typed on the card' });
    expect(onEdit).toHaveBeenCalledTimes(1);
  });

  it('sends a queued notes edit when the PARENT swaps this card away', async () => {
    // InboxPage keys the card by todo id, so promoting another queue row unmounts it — and
    // `useAutoSave` abandons a queued trailing run at unmount. Neither the resolving-write
    // flush nor the Edit flush covers this door, and it is the one triage uses most.
    let land!: (t: Todo) => void;
    updateTodoMock.mockReturnValueOnce(new Promise<Todo>(r => { land = r; }));
    render({ notes: '' });
    setValue(notesBox(), 'first');
    unfocus(notesBox());                                  // save #1 in flight
    setValue(notesBox(), 'first and the crucial second');
    unfocus(notesBox());                                  // queued behind it

    act(() => { root.render(<div />); });                 // the parent swaps the head item
    await act(async () => { land({ ...TODO, notes: 'first' }); });

    const sent = updateTodoMock.mock.calls.map(c => c[1] as Record<string, unknown>);
    expect(sent.some(f => f.notes === 'first and the crucial second')).toBe(true);
  });

  it('chains the parting write behind a notes save still in flight', async () => {
    // The parting write closes a gap in the primitive's single-flight guarantee; issuing it
    // CONCURRENTLY would reopen the very race that guarantee exists for — two writes to the
    // same column, the row going to whichever commits last, so the older draft can win.
    let land!: (t: Todo) => void;
    updateTodoMock.mockReturnValueOnce(new Promise<Todo>(r => { land = r; }));
    render({ notes: '' });
    setValue(notesBox(), 'first');
    unfocus(notesBox());
    setValue(notesBox(), 'first and second');
    unfocus(notesBox());

    act(() => { root.render(<div />); });
    expect(updateTodoMock).toHaveBeenCalledTimes(1); // nothing sent alongside the live request

    await act(async () => { land({ ...TODO, notes: 'first' }); });
    await act(async () => {});

    const sent = updateTodoMock.mock.calls.map(c => c[1] as Record<string, unknown>);
    expect(sent.some(f => f.notes === 'first and second')).toBe(true);
  });

  it('does not re-send a note still in flight when the card goes away', async () => {
    // The ordinary unmount: one save running, nothing queued. Sending again would be a
    // duplicate write of text the server already has.
    let land!: (t: Todo) => void;
    updateTodoMock.mockReturnValueOnce(new Promise<Todo>(r => { land = r; }));
    render({ notes: '' });
    setValue(notesBox(), 'only once');
    unfocus(notesBox());

    act(() => { root.render(<div />); });
    await act(async () => { land({ ...TODO, notes: 'only once' }); });

    expect(updateTodoMock.mock.calls.filter(c => 'notes' in (c[1] as object))).toHaveLength(1);
  });

  it('retries a note whose save FAILED when the card is swapped away', async () => {
    // The in-flight guard must not swallow a failed attempt: nothing reached the server, so
    // this is the one case where the parting write is the last chance the text has.
    updateTodoMock.mockRejectedValueOnce(new Error('offline'));
    render({ notes: '' });
    setValue(notesBox(), 'rescue me');
    unfocus(notesBox());
    await act(async () => {});
    updateTodoMock.mockClear();

    act(() => { root.render(<div />); });
    await act(async () => {});

    expect(updateTodoMock).toHaveBeenCalledWith(7, { notes: 'rescue me' });
  });

  it('tells the parent to reload after a parting write', async () => {
    // Without this the page's cached list still holds the pre-rescue notes: promote back to
    // this item and the box seeds from that stale copy, and the next edit overwrites the very
    // text the parting write just saved.
    render({ notes: '' });
    setValue(notesBox(), 'typed then swapped away');

    act(() => { root.render(<div />); });
    await act(async () => {});

    expect(updateTodoMock).toHaveBeenCalledWith(7, { notes: 'typed then swapped away' });
    expect(onChanged).toHaveBeenCalled();
  });

  it('does not clobber an outside note that arrived on another write\'s response', async () => {
    // Todo GTD has real concurrent writers (agents, Chatty sync, the phone PWA). A write of
    // ours answers with the row AS THE SERVER HAS IT — including a note someone else just
    // added. Recording that version without taking its content is a silent clobber: the
    // refetch that follows carries the SAME version, so it is rejected as our own echo, the
    // box goes on showing the pre-edit text, and the next blur writes it back over them.
    //
    // The assertion that matters is the last one: the outside note has to SURVIVE a later
    // blur, not merely appear on screen.
    updateTodoMock.mockResolvedValueOnce({
      ...TODO, notes: 'added from my phone', star: true, updated_at: '2026-08-06T12:10:00Z', rev: 11,
    });
    render({ notes: '' });
    click(button('★')); // any unrelated write; its response carries the outside note
    await act(async () => {});

    expect(notesBox().value).toBe('added from my phone');

    updateTodoMock.mockClear();
    unfocus(notesBox());
    await act(async () => {});

    const notesWrites = updateTodoMock.mock.calls.filter(c => 'notes' in (c[1] as object));
    expect(notesWrites).toHaveLength(0); // nothing to save — and nothing to overwrite
  });

  it('keeps unsaved text of the user\'s own when an outside note arrives', async () => {
    // The other half of the rule: adopting must never take the box away from someone who is
    // mid-sentence in it.
    updateTodoMock.mockResolvedValueOnce({
      ...TODO, notes: 'added from my phone', star: true, updated_at: '2026-08-06T12:10:00Z', rev: 11,
    });
    render({ notes: '' });
    setValue(notesBox(), 'what I was typing');
    click(button('★'));
    await act(async () => {});

    expect(notesBox().value).toBe('what I was typing');
  });

  it('replaced the read-only preview rather than rendering both', () => {
    render({ notes: 'only once' });
    expect(container.querySelectorAll('textarea[aria-label="Notes"]')).toHaveLength(1);
    // The preview was a <p> under the title; the editor is the only place notes render now.
    expect([...container.querySelectorAll('p')].some(el => el.textContent?.includes('only once')))
      .toBe(false);
    expect(notesBox().value).toBe('only once');
  });
});

describe('the step bar — numbered chip and the required star (#2613)', () => {
  const bars = () => [...container.querySelectorAll('h3')];
  /** The chip is the heading's sibling inside the bar, not part of the heading text.
   * Selected STRUCTURALLY, never by `[aria-hidden]` — the test below asserts that
   * attribute, and a selector that already required it could not fail. */
  const chip = (h3: Element) => h3.parentElement!.firstElementChild!;

  it('carries the step number in a chip, not in the heading text', () => {
    render();
    const [one, two, three] = bars();

    expect([one, two, three].map(h => chip(h).textContent)).toEqual(['01', '02', '03']);
    // The number moved OUT of the heading — the old "1. What kind of action?" prefix is gone.
    expect(one.textContent).not.toContain('1.');
    expect(two.textContent).not.toContain('2.');
    expect(three.textContent).not.toContain('3.');
    expect(one.textContent).toContain('What kind of action?');
    expect(two.textContent).toContain('Add detail (optional)');
    expect(three.textContent).toContain('Last step');
  });

  it('marks ONLY step 3 required, with a star that keeps the word for screen readers', () => {
    render();
    const [one, two, three] = bars();

    // The star replaced the word — visible glyph, and the word still there for assistive tech.
    const star = [...three.querySelectorAll('span')].find(s => s.textContent === '★');
    expect(star).toBeDefined();
    expect(star!.getAttribute('aria-hidden')).toBe('true');
    expect([...three.querySelectorAll('.sr-only')].map(s => s.textContent))
      .toEqual(['Step 3: ', ' (required)']);

    // Steps 1 and 2 are not requirements, so neither gets a star.
    for (const h of [one, two]) {
      expect([...h.querySelectorAll('span')].some(s => s.textContent === '★')).toBe(false);
    }
    // Step 2's own "(optional)" wording is untouched by all of this.
    expect(two.textContent).toContain('(optional)');
  });

  it('keeps the number and the requirement in the accessible name', () => {
    render();
    const [one, , three] = bars();

    // Both are glyph-only on screen now; the heading must still SAY them.
    expect(one.textContent).toBe('Step 1: What kind of action?');
    expect(three.textContent).toBe('Step 3: Last step — set context★ (required)');
  });

  it('hides the glyphs from assistive tech and the stand-in words from nobody', () => {
    render();
    // The contract has two halves and BOTH have to hold. The chip and the star are hidden,
    // because neither reads as anything ("zero one", "black star"). The sr-only spans that
    // say those things in words must NOT be — hide one of those and the step number, or the
    // fact that step 3 is a requirement, is silently gone for a screen-reader user while the
    // page still looks perfect. textContent alone cannot tell the two apart.
    for (const h3 of bars()) {
      expect(chip(h3).getAttribute('aria-hidden')).toBe('true');
      for (const span of h3.querySelectorAll('.sr-only')) {
        expect(span.hasAttribute('aria-hidden')).toBe(false);
      }
    }
    const star = [...bars()[2].querySelectorAll('span')].find(s => s.textContent === '★');
    expect(star!.getAttribute('aria-hidden')).toBe('true');
    // `brand-ink` clears AA on `bg-sf-bg` in both themes by itself, so no `dark:` variant.
    expect(star!.className).toContain('text-sf-accent-text');
  });
});

describe('step 2 — project fields appear only with a project', () => {
  const fields = () => container.querySelector('[data-project-fields]');
  const purpose = () => container.querySelector<HTMLInputElement>('input[aria-label="Project purpose"]')!;
  const outcome = () => container.querySelector<HTMLInputElement>('input[aria-label="Project outcome"]')!;
  const blur = (el: Element) => act(() => {
    el.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
  });

  it('shows no project fields while no project is selected', () => {
    render();
    expect(fields()).toBeNull();
    // An id the project list does not hold (still loading) describes nothing either.
    render({ project_id: 99 });
    expect(fields()).toBeNull();
  });

  it('reveals the selected project\'s area, purpose and outcome, and hides them again', () => {
    const project = { ...PROJECT, purpose: 'A kitchen we like', outcome: 'Done by spring' };
    render({ project_id: 3 }, undefined, [project]);
    expect(container.querySelector('select[aria-label="Project area"]')).toBeTruthy();
    expect(purpose().value).toBe('A kitchen we like');
    expect(outcome().value).toBe('Done by spring');

    render({ project_id: null }, undefined, [project]); // deselected
    expect(fields()).toBeNull();
  });

  it('saves an edited field to the project on blur, and only when it changed', async () => {
    render({ project_id: 3 });
    blur(purpose());
    expect(updateProjectMock).not.toHaveBeenCalled();

    setValue(outcome(), 'Cabinets in');
    blur(outcome());
    await act(async () => {});

    expect(updateProjectMock).toHaveBeenCalledWith(3, { outcome: 'Cabinets in' });
    expect(updateTodoMock).not.toHaveBeenCalled(); // the project is written, not the todo
    expect(onChanged).toHaveBeenCalledTimes(1);
    expect(onProcessed).not.toHaveBeenCalled();
  });

  it('reveals the fields for a new project and creates it with them', async () => {
    render();
    setValue(projectPicker()!, 'new');
    expect(fields()).toBeTruthy();
    setValue(projectNameInput()!, 'Garage');
    setValue(purpose(), 'Room for the car');
    submitForm(projectNameInput()!);
    await act(async () => {});

    expect(createProjectMock).toHaveBeenCalledWith(
      { name: 'Garage', area_id: null, purpose: 'Room for the car', outcome: '', visibility: 'private' },
    );
    expect(updateProjectMock).not.toHaveBeenCalled();
    expect(updateTodoMock).toHaveBeenCalledWith(7, { project_id: 9 });
  });
});

describe('filing raises one notice — the undo row', () => {
  it('queues the undo and shows no info toast', async () => {
    const info = vi.spyOn(toast, 'info');
    render();
    setValue(contextPicker(), '0');
    await act(async () => {});

    expect(updateTodoMock).toHaveBeenCalledWith(7, { context: '@calls', status: 'next_action' });
    expect(info).not.toHaveBeenCalled();
  });
});
