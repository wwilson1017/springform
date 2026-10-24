// @vitest-environment jsdom
//
// Inline edit of a Todo GTD project's name and notes (#3198).
//
// WHY THIS FILE EXISTS. The click-to-edit INTERACTION belongs to `shared/inline-edit` and is
// already pinned by `RequestTitleEditor.test.tsx`; what is specific to this surface — and
// invisible to `tsc` — is everything the gate decision turns on. That the write carries ONLY
// the field that changed (a `status` key riding along would move a project's state as a side
// effect of fixing a typo). That an unchanged value sends nothing at all. That a refusal —
// blank, duplicate, or any other server error — is VISIBLE and never leaves an unsaved value
// on screen dressed as a saved one. That a successful save revalidates the shared meta cache,
// which is what carries a rename to the Projects list, the todo rows and the edit sheet's
// project picker. And that the NOTES field, which is the `body` variant's first consumer,
// treats Enter as a newline and an emptied value as a real edit rather than a slip.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { listProjectsMock, listTodosMock, updateProjectMock, getFiltersMock } = vi.hoisted(() => ({
  listProjectsMock: vi.fn(),
  listTodosMock: vi.fn(),
  updateProjectMock: vi.fn(),
  getFiltersMock: vi.fn(),
}));

vi.mock('./api', () => ({
  listProjects: listProjectsMock,
  listTodos: listTodosMock,
  updateProject: updateProjectMock,
  getFilters: getFiltersMock,
  createTodo: vi.fn(),
  updateTodo: vi.fn(),
  createProject: vi.fn(),
  todayTodos: vi.fn().mockResolvedValue([]),
  getCaptureLink: vi.fn(),
  regenerateCaptureLink: vi.fn(),
}));

import { ProjectDetailPage } from './ProjectDetailPage';
import { ApiError } from './errors';
import { resetUndoQueue } from './undoQueue';
import type { TodoProject } from './types';
import { PROJECT_EXTRA } from './testFixtures';

function project(over: Partial<TodoProject> = {}): TodoProject {
  return { ...PROJECT_EXTRA,
    id: 7,
    name: 'Q4 lanch',
    notes: '',
    status: 'active',
    open_count: 0,
    created_at: '2026-09-01T12:00:00Z',
    updated_at: '2026-09-01T12:00:00Z',
    ...over,
  };
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  listProjectsMock.mockReset().mockResolvedValue([project()]);
  listTodosMock.mockReset().mockResolvedValue([]);
  updateProjectMock.mockReset();
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
    root.render(
      <MemoryRouter initialEntries={['/todo-gtd/projects/7']}>
        <Routes>
          <Route path="/todo-gtd/projects/:id" element={<ProjectDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );
  });
}

/** The two click-to-edit triggers, told apart by the tooltip each variant renders. */
const nameTrigger = () =>
  container.querySelector<HTMLButtonElement>('button[title="Click to rename"]')!;
const notesTrigger = () =>
  container.querySelector<HTMLButtonElement>('button[title="Click to edit"]')!;

const nameEditor = () =>
  container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Project name"]');
const notesEditor = () =>
  container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Project notes"]');

const alertText = () => container.querySelector('[role="alert"]')?.textContent ?? null;

function setValue(el: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value')?.set;
  act(() => {
    setter?.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

const press = (el: Element, key: string) => {
  act(() => { el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true })); });
};

const blur = (el: Element) => {
  act(() => { el.dispatchEvent(new FocusEvent('focusout', { bubbles: true })); });
};

async function settle() {
  await act(async () => { await Promise.resolve(); });
}

describe('ProjectDetailPage — inline name edit (#3198)', () => {
  it('writes ONLY the name, adopts the response and revalidates the shared meta', async () => {
    updateProjectMock.mockResolvedValue(project({ name: 'Q4 launch' }));
    await render();
    const metaReadsBefore = listProjectsMock.mock.calls.length;

    act(() => nameTrigger().click());
    setValue(nameEditor()!, '  Q4 launch  ');
    blur(nameEditor()!);
    await settle();

    // Only `name`: a status key riding along would move the project's state as a side
    // effect of a typo fix, which the issue forbids.
    expect(updateProjectMock).toHaveBeenCalledWith(7, { name: 'Q4 launch' });
    expect(nameTrigger().textContent).toBe('Q4 launch');
    expect(alertText()).toBeNull();
    // refreshMeta() re-reads the project list — the cache the Projects page, the todo rows
    // and TodoEditSheet's picker all render the project NAME from.
    expect(listProjectsMock.mock.calls.length).toBeGreaterThan(metaReadsBefore);
  });

  it('saves on Enter as well as on blur', async () => {
    updateProjectMock.mockResolvedValue(project({ name: 'Q4 launch' }));
    await render();

    act(() => nameTrigger().click());
    setValue(nameEditor()!, 'Q4 launch');
    press(nameEditor()!, 'Enter');
    await settle();

    expect(updateProjectMock).toHaveBeenCalledWith(7, { name: 'Q4 launch' });
  });

  it('sends nothing when the name is unchanged', async () => {
    await render();
    act(() => nameTrigger().click());
    blur(nameEditor()!);
    await settle();

    expect(updateProjectMock).not.toHaveBeenCalled();
    expect(nameTrigger().textContent).toBe('Q4 lanch');
  });

  it('refuses a blank name VISIBLY and keeps the previous one', async () => {
    // The gate is explicit that this must not revert in silence: a name that vanishes with
    // no explanation reads as the app losing the edit.
    await render();
    act(() => nameTrigger().click());
    setValue(nameEditor()!, '   ');
    blur(nameEditor()!);
    await settle();

    expect(updateProjectMock).not.toHaveBeenCalled();
    expect(nameTrigger().textContent).toBe('Q4 lanch');
    expect(alertText()).toContain('A project name is required');
  });

  it("shows the server's duplicate-name refusal and keeps the typed text editable", async () => {
    // Project names are unique case-insensitively; the service answers 400 naming the
    // conflict. Showing that sentence is the whole point — a generic failure would hide the
    // one fact the user needs. The heading must still read the last SAVED name.
    updateProjectMock.mockRejectedValue(
      new ApiError(422, 'Project "Roadmap" already exists'),
    );
    await render();

    act(() => nameTrigger().click());
    setValue(nameEditor()!, 'Roadmap');
    blur(nameEditor()!);
    await settle();

    expect(alertText()).toBe('Project "Roadmap" already exists');
    expect(nameEditor()).not.toBeNull();
    expect(nameEditor()!.value).toBe('Roadmap');
  });

  it('clears the failure line once a later save succeeds', async () => {
    updateProjectMock
      .mockRejectedValueOnce(new ApiError(422, 'Project "Roadmap" already exists'))
      .mockResolvedValueOnce(project({ name: 'Q4 launch' }));
    await render();

    act(() => nameTrigger().click());
    setValue(nameEditor()!, 'Roadmap');
    blur(nameEditor()!);
    await settle();
    expect(alertText()).not.toBeNull();

    setValue(nameEditor()!, 'Q4 launch');
    blur(nameEditor()!);
    await settle();

    expect(alertText()).toBeNull();
    expect(nameTrigger().textContent).toBe('Q4 launch');
  });

  it('explains a failure that carries no server sentence', async () => {
    // Everything else here rejects with an ApiError whose `detail` is the sentence to show. A
    // dropped connection is not that, and the user still has to be told the edit did not land
    // — `apiErrorMessage` falls back to the thrown error's own message.
    updateProjectMock.mockRejectedValue(new Error('Failed to fetch'));
    await render();

    act(() => nameTrigger().click());
    setValue(nameEditor()!, 'Q4 launch');
    blur(nameEditor()!);
    await settle();

    expect(alertText()).toBe('Failed to fetch');
    expect(nameEditor()!.value).toBe('Q4 launch');
  });

  it('does not let a slower sibling write revert a field that already saved', async () => {
    // Both editors write through one handler and neither blocks the other, so two PUTs can be
    // in flight at once — and each resolves with the FULL row as the server read it back.
    // Adopting a response wholesale lets the SLOWER one carry the other field's pre-write
    // value and wipe an edit the user already watched save.
    let releaseName: (p: TodoProject) => void = () => {};
    updateProjectMock
      // The name write: held open, and its row still carries the OLD notes.
      .mockImplementationOnce(() => new Promise<TodoProject>(res => { releaseName = res; }))
      // The notes write: lands first, carrying both the new name and the new notes.
      .mockResolvedValueOnce(project({ name: 'Q4 launch', notes: 'ship by 12/1' }));
    await render();

    act(() => nameTrigger().click());
    setValue(nameEditor()!, 'Q4 launch');
    blur(nameEditor()!);
    await settle();

    act(() => notesTrigger().click());
    setValue(notesEditor()!, 'ship by 12/1');
    blur(notesEditor()!);
    await settle();
    expect(notesTrigger().textContent).toBe('ship by 12/1');

    // Now the name write finally answers, with the notes as they were BEFORE the second write.
    await act(async () => { releaseName(project({ name: 'Q4 launch', notes: '' })); });
    await settle();

    expect(notesTrigger().textContent).toBe('ship by 12/1');
    expect(nameTrigger().textContent).toBe('Q4 launch');
  });

  it('discards the edit on Escape without writing', async () => {
    await render();
    act(() => nameTrigger().click());
    setValue(nameEditor()!, 'half-typed');
    press(nameEditor()!, 'Escape');
    await settle();

    expect(updateProjectMock).not.toHaveBeenCalled();
    expect(nameTrigger().textContent).toBe('Q4 lanch');
    expect(alertText()).toBeNull();
  });
});

describe('ProjectDetailPage — inline notes edit (#3198)', () => {
  it('offers a clickable placeholder when the project has no notes', async () => {
    // Before this the notes element was not rendered AT ALL when blank, so a project with no
    // notes had nothing to click and notes could never be added after creation.
    await render();
    expect(notesTrigger().textContent).toBe('Add notes…');

    act(() => notesTrigger().click());
    expect(notesEditor()).not.toBeNull();
  });

  it('writes ONLY the notes on blur', async () => {
    updateProjectMock.mockResolvedValue(project({ notes: 'ship by 12/1' }));
    await render();

    act(() => notesTrigger().click());
    setValue(notesEditor()!, 'ship by 12/1');
    blur(notesEditor()!);
    await settle();

    expect(updateProjectMock).toHaveBeenCalledWith(7, { notes: 'ship by 12/1' });
    expect(notesTrigger().textContent).toBe('ship by 12/1');
  });

  it('treats Enter as a newline rather than a save', async () => {
    // The one behaviour the `body` variant exists for: notes are multi-line, so the keystroke
    // that ends a line must not also end the edit. Blur and Escape are the only exits.
    await render();
    act(() => notesTrigger().click());
    setValue(notesEditor()!, 'first line');
    press(notesEditor()!, 'Enter');
    await settle();

    expect(updateProjectMock).not.toHaveBeenCalled();
    expect(notesEditor()).not.toBeNull();
  });

  it('sends nothing when an empty notes field is opened and left alone', async () => {
    // The no-op half of the empty-is-legal rule: `body` lets a blank value through to a save,
    // so without the unchanged check merely tapping the placeholder would issue a write.
    await render();
    act(() => notesTrigger().click());
    blur(notesEditor()!);
    await settle();

    expect(updateProjectMock).not.toHaveBeenCalled();
    expect(notesTrigger().textContent).toBe('Add notes…');
  });

  it('clears stored notes when the field is emptied', async () => {
    listProjectsMock.mockResolvedValue([project({ notes: 'stale draft' })]);
    updateProjectMock.mockResolvedValue(project({ notes: '' }));
    await render();
    expect(notesTrigger().textContent).toBe('stale draft');

    act(() => notesTrigger().click());
    setValue(notesEditor()!, '');
    blur(notesEditor()!);
    await settle();

    expect(updateProjectMock).toHaveBeenCalledWith(7, { notes: '' });
    expect(notesTrigger().textContent).toBe('Add notes…');
  });

  it('stores notes verbatim, indentation and trailing newline included', async () => {
    // `validate_notes` returns the text untouched, so trimming on the way out would rewrite
    // what the user typed — the indent on the first line of a list, and every trailing blank
    // line. Only an ENTIRELY blank draft normalizes to empty, so the placeholder comes back.
    const typed = '  - call the printer\n  - confirm ship date\n';
    updateProjectMock.mockResolvedValue(project({ notes: typed }));
    await render();

    act(() => notesTrigger().click());
    setValue(notesEditor()!, typed);
    blur(notesEditor()!);
    await settle();

    expect(updateProjectMock).toHaveBeenCalledWith(7, { notes: typed });
  });

  it('keeps a failed name save on screen when the notes editor closes unchanged', async () => {
    // The sequence, which needs both editors open at once: clicking the notes trigger is what
    // blurs the name editor, so the name save is already in flight when notes opens and takes
    // focus. The refusal then leaves the name editor open and pulls focus BACK to it — which
    // blurs notes, closing it unchanged. An untagged failure line is cleared by that close,
    // leaving the user's rejected text on screen with nothing explaining why it did not save.
    let rejectName: (e: unknown) => void = () => {};
    updateProjectMock.mockImplementationOnce(
      () => new Promise<TodoProject>((_res, rej) => { rejectName = rej; }),
    );
    await render();

    act(() => nameTrigger().click());
    setValue(nameEditor()!, 'Roadmap');
    blur(nameEditor()!); // the save starts and stays pending; the editor stays open
    await settle();

    act(() => notesTrigger().click());
    expect(notesEditor()).not.toBeNull();

    await act(async () => {
      rejectName(new ApiError(422, 'Project "Roadmap" already exists'));
    });
    await settle();

    expect(alertText()).toBe('Project "Roadmap" already exists');
  });

  it('discards a notes edit on Escape', async () => {
    listProjectsMock.mockResolvedValue([project({ notes: 'keep me' })]);
    await render();

    act(() => notesTrigger().click());
    setValue(notesEditor()!, 'throw me away');
    press(notesEditor()!, 'Escape');
    await settle();

    expect(updateProjectMock).not.toHaveBeenCalled();
    expect(notesTrigger().textContent).toBe('keep me');
  });
});

describe('ProjectDetailPage — add a next action', () => {
  it('keeps the typed text and says why when the add is refused', async () => {
    const { createTodo } = await import('./api');
    vi.mocked(createTodo).mockReset().mockRejectedValue(
      new ApiError(422, 'This list is full.'),
    );
    await render();
    const input = container.querySelector<HTMLInputElement>(
      'input[placeholder^="Add a next action"]',
    )!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    act(() => {
      setter?.call(input, 'Email the caterer');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      input.form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    expect(createTodo).toHaveBeenCalledTimes(1);
    expect(input.value).toBe('Email the caterer');
    expect(document.body.textContent).toContain('This list is full.');
  });
});
