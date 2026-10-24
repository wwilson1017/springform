// Who sees a todo and who it is for. The server owns the rules and refuses with a sentence; the
// screens must show a team row's owner and assignee, offer only an assignee a private row can
// take, send the change as one patch, and put the server's refusal in front of the user.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { updateTodoMock, createTodoMock } = vi.hoisted(() => ({ updateTodoMock: vi.fn(), createTodoMock: vi.fn() }));
vi.mock('../api', () => ({ updateTodo: updateTodoMock, createTodo: createTodoMock, projectIdFor: vi.fn() }));
const { filters } = vi.hoisted(() => ({ filters: { current: null as unknown } }));
vi.mock('../useTodoMeta', () => ({ useListFilters: () => filters.current, useListTz: () => undefined }));

import { ApiError } from '../errors';
import { MeContext } from '../me';
import { filtersOf, ITEM_EXTRA, OWNER } from '../testFixtures';
import type { Todo } from '../types';
import { SharingFields } from './Sharing';
import { TodoEditSheet } from './TodoEditSheet';
import { TodoRow } from './TodoRow';

const TODO: Todo = {
  ...ITEM_EXTRA, id: 7, title: 'Order new aprons', notes: '', project_id: null, project_name: null, context: '',
  tags: [], status: 'next_action', star: false, due_date: null, repeat: '', auto_star_on_due: false, source: 'ui',
  created_at: '2026-10-01T12:00:00Z', updated_at: '2026-10-01T12:00:00Z', completed_at: null,
};
const MEMBERS = filtersOf().members;

beforeEach(() => {
  updateTodoMock.mockReset().mockResolvedValue(TODO);
  createTodoMock.mockReset().mockResolvedValue(TODO);
  filters.current = filtersOf();
});

const noop = () => {};

describe('a team row on a list', () => {
  it('shows its owner and assignee; a private row shows neither', () => {
    const { rerender, container } = render(
      <TodoRow todo={{ ...TODO, visibility: 'team', owner_name: 'Ann Owner', assignee_user_id: 2, assignee_name: 'Bo Member' }}
               onToggleDone={noop} onToggleStar={noop} onEdit={noop} />);
    expect(container.querySelector('[data-team]')!.textContent).toBe('Team · Ann Owner → Bo Member');

    rerender(<TodoRow todo={{ ...TODO, visibility: 'team', owner_name: 'Ann Owner' }}
                      onToggleDone={noop} onToggleStar={noop} onEdit={noop} />);
    expect(container.querySelector('[data-team]')!.textContent).toBe('Team · Ann Owner');

    rerender(<TodoRow todo={TODO} onToggleDone={noop} onToggleStar={noop} onEdit={noop} />);
    expect(container.querySelector('[data-team]')).toBeNull();
  });
});

describe('the sharing fields', () => {
  it('offers a private row only nobody or its owner, and a team row everyone', () => {
    const { rerender } = render(<SharingFields idPrefix="t" visibility="private" assignee={null} ownerId={OWNER}
                                               members={MEMBERS} onChange={noop} />);
    const options = () => [...screen.getByLabelText('Assigned to').querySelectorAll('option')].map(o => o.textContent);
    expect(options()).toEqual(['Nobody', 'Ann Owner']);
    rerender(<SharingFields idPrefix="t" visibility="team" assignee={null} ownerId={OWNER} members={MEMBERS} onChange={noop} />);
    expect(options()).toEqual(['Nobody', 'Ann Owner', 'Bo Member']);
  });

  it('making a row private drops an assignee who is not its owner, in the same change', () => {
    const onChange = vi.fn();
    render(<SharingFields idPrefix="t" visibility="team" assignee={2} ownerId={OWNER} members={MEMBERS} onChange={onChange} />);
    fireEvent.click(screen.getByRole('radio', { name: 'Only me' }));
    expect(onChange).toHaveBeenCalledWith({ visibility: 'private', assignee_user_id: null });
  });
});

function sheet(todo: Todo | null) {
  return render(
    <MemoryRouter>
      <MeContext.Provider value={{ id: OWNER, isAdmin: false }}>
        <TodoEditSheet todo={todo} projects={[]} contexts={[]} onClose={noop} onSaved={noop} />
      </MeContext.Provider>
    </MemoryRouter>,
  );
}

describe('the edit sheet', () => {
  it('starts a new todo at the install default and sends visibility only once picked', async () => {
    filters.current = filtersOf({ default_visibility: 'team' });
    const first = sheet(null);
    expect(screen.getByRole('radio', { name: 'Team' }).getAttribute('aria-checked')).toBe('true');
    fireEvent.change(screen.getByLabelText(/next action/), { target: { value: 'Book the van' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(createTodoMock).toHaveBeenCalled());
    expect(createTodoMock.mock.calls[0][0]).not.toHaveProperty('visibility'); // the server applies the default
    first.unmount();

    sheet(null);
    fireEvent.change(screen.getByLabelText(/next action/), { target: { value: 'Book the van' } });
    fireEvent.click(screen.getByRole('radio', { name: 'Only me' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(createTodoMock).toHaveBeenCalledTimes(2));
    expect(createTodoMock.mock.calls[1][0]).toMatchObject({ visibility: 'private', assignee_user_id: null });
  });

  it('assigns a team todo, and shows its owner', async () => {
    sheet({ ...TODO, visibility: 'team', owner_name: 'Ann Owner' });
    expect(screen.getByText(/Owner: Ann Owner/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Assigned to'), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(updateTodoMock).toHaveBeenCalled());
    expect(updateTodoMock.mock.calls[0][1]).toMatchObject({ visibility: 'team', assignee_user_id: 2 });
  });

  it("puts the server's refusal in front of the user and keeps the form", async () => {
    updateTodoMock.mockRejectedValue(new ApiError(403, 'Only the owner can make this todo private.'));
    sheet({ ...TODO, visibility: 'team', owner_user_id: 2 });
    fireEvent.click(screen.getByRole('radio', { name: 'Only me' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe('Only the owner can make this todo private.');
    expect(within(screen.getByRole('radiogroup')).getByRole('radio', { name: 'Only me' }).getAttribute('aria-checked')).toBe('true');
  });
});
