import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, mockFetch } from '../../testing';
import { ChangeListView } from './ChangeListView';
import { ToolConfirmCard } from './ToolConfirmCard';

afterEach(() => vi.unstubAllGlobals());

const row = (id: number, title: string) => ({
  entity_type: 'todos.item',
  entity_id: id,
  title,
  field: 'visibility',
  old: 'team',
  new: 'private',
});
const LIST = {
  tool_run_id: 7,
  status: 'applied',
  rows: [row(1, 'Order flour'), row(2, 'Call the plumber')],
  notes: ['1 repeating todos get their next occurrence; Undo cannot take that back.'],
  hidden: 0,
  reverted: null,
  skipped: [],
};
const UNDONE = {
  ...LIST,
  status: 'undone',
  reverted: 1,
  skipped: [
    { entity_type: 'todos.item', entity_id: 2, title: 'Call the plumber', reason: 'changed since it was applied' },
  ],
};

describe('ChangeListView', () => {
  it('lists old → new with the notes, and Undo shows what was put back and what was left', async () => {
    const fetchMock = mockFetch({
      'GET /api/agent/change-lists/7': { body: LIST },
      'POST /api/agent/change-lists/7/undo': { body: UNDONE },
    });
    render(<ChangeListView runId={7} />);
    expect(await screen.findByText('2 changes on 2 records')).toBeTruthy();
    expect(screen.getByText('Order flour · visibility: team → private')).toBeTruthy();
    expect(screen.getByText(/repeating todos/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(await screen.findByText('Undone: 1 put back.')).toBeTruthy();
    expect(screen.getByText('Call the plumber: left as it is (changed since it was applied)')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull();
    expect(callsTo(fetchMock, 'POST', '/api/agent/change-lists/7/undo')).toHaveLength(1);
  });

  it('shows the first 20 rows until Show all', async () => {
    const rows = Array.from({ length: 25 }, (_, i) => row(i + 1, `Todo ${i + 1}`));
    mockFetch({ 'GET /api/agent/change-lists/7': { body: { ...LIST, rows, notes: [] } } });
    render(<ChangeListView runId={7} />);
    expect(await screen.findByText('Todo 20 · visibility: team → private')).toBeTruthy();
    expect(screen.queryByText('Todo 21 · visibility: team → private')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Show all 25' }));
    expect(screen.getByText('Todo 25 · visibility: team → private')).toBeTruthy();
  });

  it('keeps the Undo button with the reason when the server refuses', async () => {
    mockFetch({
      'GET /api/agent/change-lists/7': { body: LIST },
      'POST /api/agent/change-lists/7/undo': { status: 409, body: { detail: 'already_undone' } },
    });
    render(<ChangeListView runId={7} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Undo' }));
    expect(await screen.findByText('Undo failed: already undone')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Undo' })).toBeTruthy();
  });

  it('shows an undone list from the server as undone', async () => {
    mockFetch({ 'GET /api/agent/change-lists/7': { body: UNDONE } });
    render(<ChangeListView runId={7} />);
    expect(await screen.findByText('Undone: 1 put back.')).toBeTruthy();
  });

  it('keeps Approve disabled on its card until the list has loaded', async () => {
    mockFetch({ 'GET /api/agent/change-lists/7': { body: { ...LIST, status: 'staged' } } });
    render(
      <ToolConfirmCard
        part={{
          kind: 'tool',
          tool: 'todos_bulk_update',
          toolUseId: 'u',
          args: {},
          status: 'pending',
          runId: 7,
          changeList: true,
          confirm: { phase: 'pending' },
        }}
        onDecide={() => {}}
      />,
    );
    const approve = screen.getByRole('button', { name: 'Approve' }) as HTMLButtonElement;
    expect(approve.disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Deny' }) as HTMLButtonElement).disabled).toBe(false);
    await waitFor(() => expect(approve.disabled).toBe(false));
    expect(screen.getByText('2 changes on 2 records')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull(); // staged: nothing to undo yet
  });
});
