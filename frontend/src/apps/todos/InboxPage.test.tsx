// @vitest-environment jsdom
//
// The half of issue todo-gtd #1548 that does NOT live in TriageCard: which callback the inbox page
// hands the card, and the `key` that scopes the card's local state to one item.
//
// Both are silent failures. The page used to pass ONE callback that cleared the manual
// selection on every change, so an in-place edit bounced a hand-picked item back to the
// head of the list — harmless-looking before todo-gtd #1548, but now Step 1 and the title edit are
// both in-place, so triage would jump to a different todo mid-clarify. And because the
// chosen destination is local state, a missing `key` would carry "Waiting" from the item
// you just filed onto the next one, silently mis-filing it.
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
  todayTodos: vi.fn().mockResolvedValue([]),
  createTodo: vi.fn(),
  listProjects: vi.fn().mockResolvedValue([]),
  createProject: vi.fn(),
  updateProject: vi.fn(),
  getFilters: vi.fn().mockResolvedValue({ contexts: ['@calls'], tags: [], status_counts: {} }),
  getCaptureLink: vi.fn(),
  regenerateCaptureLink: vi.fn(),
}));

import { InboxPage } from './InboxPage';
import type { Todo } from './types';
import { notifyTodosChanged, resetInboxFocus } from './hooks';
import { resetUndoQueue } from './undoQueue';
import { ITEM_EXTRA } from './testFixtures';

const base: Omit<Todo, 'id' | 'title'> = { ...ITEM_EXTRA,
  notes: '', project_id: null, project_name: null, context: '', tags: [],
  status: 'inbox', star: false, due_date: null, repeat: '',
  auto_star_on_due: false, source: 'ui',
  created_at: '2026-08-06T12:00:00Z', updated_at: '2026-08-06T12:00:00Z', completed_at: null,
};
const FIRST: Todo = { ...base, id: 1, title: 'first captured' };
const SECOND: Todo = { ...base, id: 2, title: 'second captured' };

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  listTodosMock.mockReset().mockResolvedValue([FIRST, SECOND]);
  updateTodoMock.mockReset().mockResolvedValue(FIRST);
  resetUndoQueue();
  resetInboxFocus();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  resetUndoQueue();
});

async function render() {
  await act(async () => {
    root.render(<MemoryRouter><InboxPage /></MemoryRouter>);
  });
}

/** The item currently on the big triage card (its click-to-rename title). */
const onCard = () =>
  container.querySelector('.rounded-xl')?.querySelector('button[title="Click to rename"]')
    ?.textContent ?? null;

/** The compact "N more in inbox" rows below the card.
 *
 * Keyed on the list's `data-inbox-queue` marker, not on a Tailwind class: this
 * used to select `button.truncate` and went silently empty the moment those
 * titles were changed to wrap. */
const restRows = () =>
  [...container.querySelectorAll<HTMLButtonElement>('[data-inbox-queue] button')];

function button(label: string): HTMLButtonElement {
  const found = [...container.querySelectorAll('button')].find(
    b => (b.textContent ?? '').trim() === label,
  );
  if (!found) throw new Error(`no button labelled "${label}"`);
  return found;
}

const click = (el: Element) => act(() => { (el as HTMLElement).click(); });

describe('InboxPage triage selection', () => {
  it('keeps a manually selected item on the card through an in-place change', async () => {
    await render();
    expect(onCard()).toBe('first captured');

    click(restRows()[0]); // promote "second captured"
    expect(onCard()).toBe('second captured');

    // Star it — an in-place change. The card must not jump back to the head.
    click(button('★'));
    await act(async () => {});

    expect(updateTodoMock).toHaveBeenCalledWith(2, { star: true });
    expect(onCard()).toBe('second captured');
  });

  it('advances to the next item once one is filed', async () => {
    await render();
    click(restRows()[0]);
    expect(onCard()).toBe('second captured');

    listTodosMock.mockResolvedValue([FIRST]); // the filed item is gone on reload
    const picker = container.querySelector<HTMLSelectElement>(
      'select[aria-label="Set context and file this todo"]',
    )!;
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(picker), 'value')?.set;
    await act(async () => {
      setter?.call(picker, '0');
      picker.dispatchEvent(new Event('change', { bubbles: true }));
    });

    expect(updateTodoMock).toHaveBeenCalledWith(2, { context: '@calls', status: 'next_action' });
    expect(onCard()).toBe('first captured');
  });

  it('shows ONE notice for a filing: the undo row, inline between the card and the queue', async () => {
    const third = { ...SECOND, id: 3, title: 'third captured' };
    listTodosMock.mockResolvedValue([FIRST, SECOND, third]);
    await render();

    listTodosMock.mockResolvedValue([SECOND, third]); // FIRST is filed and gone
    const picker = container.querySelector<HTMLSelectElement>(
      'select[aria-label="Set context and file this todo"]',
    )!;
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(picker), 'value')?.set;
    await act(async () => {
      setter?.call(picker, '0');
      picker.dispatchEvent(new Event('change', { bubbles: true }));
    });

    const notices = [...container.querySelectorAll('[role="status"]')]
      .filter(n => (n.textContent ?? '').trim() !== '');
    expect(notices).toHaveLength(1); // no second "Filed under…" toast
    const pill = notices[0];
    expect(pill.getAttribute('aria-label')).toBe('Recent changes you can undo');
    expect(pill.textContent).toContain('first captured');
    expect(pill.querySelector('button')).toBeTruthy();
    // In the page flow — not in the shell's floating stack — after the card, before the queue.
    expect(pill.closest('.fixed')).toBeNull();
    const card = container.querySelector('button[title="Click to rename"]')!;
    const queue = container.querySelector('[data-inbox-queue]')!;
    expect(card.compareDocumentPosition(pill) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(pill.compareDocumentPosition(queue) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('leaves the queue rows promote-only — no inline rename anywhere but the card', async () => {
    // That list is one "triage this one next" target per row. An edit box opening
    // mid-row makes skipping between items fiddly, and the item is about to land
    // on the card, where renaming belongs. Chatty locked this explicitly when its
    // TodoRow gained click-to-rename (chatty#146); CAKE's rows must never acquire
    // it in the first place, and nothing but a test can say so.
    await render();
    expect(restRows()).toHaveLength(1);

    // The card's title is the ONE rename affordance on the page.
    expect(container.querySelectorAll('button[title="Click to rename"]')).toHaveLength(1);

    click(restRows()[0]); // promoting is all a queue-row click does
    expect(container.querySelector('textarea[aria-label="Todo title"]')).toBeNull();
    expect(onCard()).toBe('second captured');
    expect(updateTodoMock).not.toHaveBeenCalled();
  });

  it('does not carry one item\'s chosen destination onto the next', async () => {
    await render();
    click(restRows()[0]);
    click(button('Waiting'));
    expect(button('Waiting').getAttribute('aria-pressed')).toBe('true');

    // Back to the head item: a different card, so a fresh destination.
    click(restRows()[0]);
    expect(onCard()).toBe('first captured');
    expect(button('Waiting').getAttribute('aria-pressed')).toBe('false');
    expect(button('Next action').getAttribute('aria-pressed')).toBe('true');
  });
});

describe('InboxPage capture box', () => {
  const captureBox = () =>
    [...container.querySelectorAll<HTMLInputElement>('input[placeholder^="Add to inbox"]')];

  it('renders once, in the page body below the filter bar', async () => {
    // The shell's copy is suppressed (hideQuickAdd) and this page renders its own
    // under the filters, next to the card being triaged. Two live instances would
    // mean two half-typed captures and a stale one silently winning.
    await render();
    expect(captureBox()).toHaveLength(1);

    const filter = container.querySelector('input[placeholder="Search inbox…"]')!;
    const following = filter.compareDocumentPosition(captureBox()[0]);
    expect(following & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

// ── todo-gtd #2925 — where an undone filing lands ────────────────────────────────────
//
// The build-time decision on that issue: undoing a context selection must
// re-surface the item AS THE CURRENT TRIAGE CARD, not correct it silently in the
// background. Triage is not a list — the item does not simply reappear in a row
// the user is already looking at, it goes back into a queue whose head is picked
// by the page. Both cases below pass with the revert wired up and the card left
// alone, which is exactly why they exist.

/** The card's context picker — the affordance that has to still work afterwards. */
const picker = () =>
  container.querySelector<HTMLSelectElement>('select[aria-label="Set context and file this todo"]')!;

/** File whatever is on the card under the first offered context. */
async function fileFromCard() {
  const el = picker();
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value')?.set;
  await act(async () => {
    setter?.call(el, '0');
    el.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

async function clickUndoFiling(title: string) {
  const el = container.querySelector<HTMLButtonElement>(`button[aria-label="Undo filing “${title}”"]`);
  if (!el) throw new Error(`no filing-undo button for "${title}"`);
  await act(async () => { el.click(); });
}

describe('InboxPage — undoing a filing (todo-gtd #2925)', () => {
  it('promotes the restored item to the card instead of leaving it down the queue', async () => {
    await render();
    click(restRows()[0]); // triage "second captured", which is NOT the head
    expect(onCard()).toBe('second captured');

    listTodosMock.mockResolvedValue([FIRST]); // filed, so it leaves the inbox
    await fileFromCard();
    expect(updateTodoMock).toHaveBeenCalledWith(2, { context: '@calls', status: 'next_action' });
    expect(onCard()).toBe('first captured');

    listTodosMock.mockResolvedValue([FIRST, SECOND]); // and it comes back
    await clickUndoFiling('second captured');

    // The point of the issue. `items[0]` is "first captured"; without the page
    // taking the focus the undo would be invisible and the user would have no
    // way to see it took effect.
    expect(updateTodoMock).toHaveBeenLastCalledWith(2, { status: 'inbox', context: '' });
    expect(onCard()).toBe('second captured');
  });

  it('gives the restored item a working card even when the undo outran the refetch', async () => {
    // `TriageCard` stays `busy` after a resolving write on purpose — it is spent,
    // and it counts on the reload swapping in a different head item to remount
    // it. But `useTodos` cancels a superseded fetch, so an undo clicked inside
    // that window cancels the filing's refetch: the list never drops the item,
    // and the same spent card would still be mounted under the same id with its
    // picker disabled — an item back in the inbox that cannot be triaged again.
    await render();
    expect(onCard()).toBe('first captured'); // file the HEAD, so the id does not change

    await fileFromCard(); // listTodos still answers [FIRST, SECOND]
    expect(updateTodoMock).toHaveBeenCalledWith(1, { context: '@calls', status: 'next_action' });
    expect(picker().disabled).toBe(true); // spent, as designed

    await clickUndoFiling('first captured');

    expect(onCard()).toBe('first captured');
    expect(picker().disabled).toBe(false);
  });

  it('clears a filter the restored item would otherwise be hidden behind', async () => {
    // Reachable because `TodoEditSheet` files an inbox item too, and THAT write
    // carries the title as well — so an item renamed while being filed comes back
    // wearing a title the active search no longer matches. Selecting it would then
    // fall straight through to `items[0]` and the undo would look like a no-op.
    await render();
    const search = container.querySelector<HTMLInputElement>('input[placeholder="Search inbox…"]')!;
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(search), 'value')?.set;
    await act(async () => {
      setter?.call(search, 'first');
      search.dispatchEvent(new Event('input', { bubbles: true }));
    });
    // `SearchInput` settles the query through a 250ms debounce before the page
    // ever sees it, so asserting on the unsettled box would pass against no filter
    // at all — which is what the first draft of this test did.
    await act(async () => { await new Promise(r => setTimeout(r, 300)); });
    // The filter is real: only FIRST is on the card, SECOND is filtered away.
    expect(onCard()).toBe('first captured');
    expect(restRows()).toHaveLength(0);

    act(() => { notifyTodosChanged(2); }); // an undo restores "second captured"

    expect(onCard()).toBe('second captured');
    expect(search.value).toBe('');
  });

  it('takes a focus raised while the Inbox was not even mounted', async () => {
    // The pill outlives the shell — `TodoShell` unmounts on every tab switch, so
    // a filing undone from Today has no InboxPage listening at all. The request
    // has to wait for the page rather than be broadcast into nothing, or walking
    // back to the Inbox lands on whatever `items[0]` is and the correction the
    // user asked for is invisible. `notifyTodosChanged` is the seam the undo path
    // reaches the pages through; this drives it directly because the whole point
    // is that no page is mounted at the time.
    act(() => { notifyTodosChanged(2); });

    await render();

    expect(onCard()).toBe('second captured');
  });
});

describe('InboxPage — the inline undo notice and the edit sheet', () => {
  /** Every rendered undo block, floating or inline — they share one accessible name. */
  const undoBlocks = () =>
    [...container.querySelectorAll('[aria-label="Recent changes you can undo"]')];

  it('hands the notice to the floating copy while the edit sheet covers the page', async () => {
    await render();
    listTodosMock.mockResolvedValue([SECOND]); // FIRST is filed and gone
    await fileFromCard();
    expect(undoBlocks()).toHaveLength(1);
    expect(undoBlocks()[0].closest('.fixed')).toBeNull(); // inline, in the page flow

    // Opening the sheet on the next card puts a full-page overlay over that inline row
    // while its 7s window keeps running.
    click(button('Edit'));
    await act(async () => {});
    const sheet = [...container.querySelectorAll('h2')]
      .find(h => h.textContent === 'Edit todo')!.closest('.fixed')!;

    // Still ONE block, now in the shell's floating stack — which is rendered after the
    // sheet, so it paints above the overlay — and its Undo still works from there.
    const blocks = undoBlocks();
    expect(blocks).toHaveLength(1);
    const stack = blocks[0].closest('.fixed');
    expect(stack).not.toBeNull();
    expect(stack).not.toBe(sheet);
    expect(sheet.compareDocumentPosition(stack!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    listTodosMock.mockResolvedValue([FIRST, SECOND]);
    await clickUndoFiling('first captured');
    expect(updateTodoMock).toHaveBeenLastCalledWith(1, { status: 'inbox', context: '' });
  });

  it('brings the notice back inline when the sheet closes', async () => {
    await render();
    listTodosMock.mockResolvedValue([SECOND]);
    await fileFromCard();
    click(button('Edit'));
    await act(async () => {});
    expect(undoBlocks()[0].closest('.fixed')).not.toBeNull();

    click(button('Cancel'));

    expect(undoBlocks()).toHaveLength(1);
    expect(undoBlocks()[0].closest('.fixed')).toBeNull();
  });

  it('puts a two-minute completion back on the card when it is undone', async () => {
    // "Took 2 minutes — Done ✓" completes straight from triage, so its undo lands the
    // item back in the inbox exactly as a filing's does — and it has to come back as
    // the current card for the same reason: `items[0]` is something else.
    await render();
    click(restRows()[0]); // triage "second captured", which is NOT the head
    listTodosMock.mockResolvedValue([FIRST]);
    click(button('Took 2 minutes — Done ✓'));
    await act(async () => {});
    expect(updateTodoMock).toHaveBeenCalledWith(2, { status: 'done' });
    expect(onCard()).toBe('first captured');

    listTodosMock.mockResolvedValue([FIRST, SECOND]);
    const undo = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Undo marking “second captured” done"]')!;
    await act(async () => { undo.click(); });

    expect(updateTodoMock).toHaveBeenLastCalledWith(2, { status: 'inbox' });
    expect(onCard()).toBe('second captured');
  });
});
