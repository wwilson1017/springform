// Mine or Everyone: the working lists ask the server for the caller's work (`mine=true`) unless
// the switch says Everyone, and the feed's rows are sorted into a list by the same rule.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { listTodosMock } = vi.hoisted(() => ({ listTodosMock: vi.fn() }));
vi.mock('./api', () => ({ listTodos: listTodosMock, updateTodo: vi.fn() }));

import { useStatusList } from './hooks';
import { MeContext } from './me';
import { isMine, setScope, useScope } from './scope';

describe('isMine', () => {
  const row = (visibility: 'private' | 'team', owner: number, assignee: number | null) =>
    ({ visibility, owner_user_id: owner, assignee_user_id: assignee });

  it("is the server's work rule: my private rows, team rows for me or for nobody", () => {
    expect(isMine(row('private', 1, null), 1)).toBe(true);
    expect(isMine(row('private', 2, null), 1)).toBe(false);
    expect(isMine(row('team', 2, null), 1)).toBe(true);
    expect(isMine(row('team', 2, 1), 1)).toBe(true);
    expect(isMine(row('team', 1, 2), 1)).toBe(false); // mine to own, someone else's to do
  });
});

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  listTodosMock.mockReset().mockResolvedValue([]);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  setScope('mine');
});

function Inbox() {
  useStatusList('inbox', useScope());
  return null;
}

describe('useStatusList', () => {
  it('asks for my work, then for everything once the switch says Everyone', async () => {
    await act(async () => { root.render(<MeContext.Provider value={{ id: 1, isAdmin: false }}><Inbox /></MeContext.Provider>); });
    expect(listTodosMock).toHaveBeenLastCalledWith({ status: 'inbox', limit: 500, mine: true });
    await act(async () => { setScope('all'); });
    expect(listTodosMock).toHaveBeenLastCalledWith({ status: 'inbox', limit: 500 });
  });
});
