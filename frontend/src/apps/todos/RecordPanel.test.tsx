// The Todos panel on a person's page, through the real api.ts and core client against a stubbed
// fetch: it lists what /for/{type}/{id} answers, the include-done toggle asks again, and its
// quick add links the new todo to the record.
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider } from '../../core/auth/AuthContext';
import { callsTo, mockFetch } from '../../testing';
import TodosRecordPanel from './RecordPanel';
import { filtersOf, ITEM_EXTRA } from './testFixtures';
import type { Todo } from './types';

const ME = { id: 1, email: 'ann@example.com', name: 'Ann Owner', role: 'member', tz: 'America/Chicago' };
const row = (id: number, title: string, over: Partial<Todo> = {}): Todo => ({
  ...ITEM_EXTRA, id, title, notes: '', project_id: null, project_name: null, context: '', tags: [],
  status: 'next_action', star: false, due_date: null, repeat: '', auto_star_on_due: false, source: 'ui',
  created_at: '2026-10-01T12:00:00Z', updated_at: '2026-10-01T12:00:00Z', completed_at: null,
  entity_type: 'core.person', entity_id: 5, ...over,
});
const OPEN = row(1, 'Call about the order', { visibility: 'team', owner_name: 'Bo Member' });
const DONE = row(2, 'Send the quote', { status: 'done', completed_at: '2026-10-02T12:00:00Z' });

afterEach(() => { vi.unstubAllGlobals(); });

function panel() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <TodosRecordPanel entityType="core.person" entityId={5} />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('the To-dos panel on a record', () => {
  it("lists the record's open todos, and the done ones on request", async () => {
    const fetch = mockFetch({
      'GET /api/me': { body: ME },
      'GET /api/todos/for/core.person/5': { body: [OPEN] },
      'GET /api/todos/for/core.person/5?include_done=true': { body: [OPEN, DONE] },
      'GET /api/todos/filters': { body: filtersOf() },
      'GET /api/todos/projects': { body: [] },
    });
    panel();
    expect(await screen.findByText('Call about the order')).toBeTruthy();
    expect(screen.getByText('Team · Bo Member')).toBeTruthy();
    expect(screen.queryByText('Send the quote')).toBeNull();

    fireEvent.click(screen.getByLabelText('Show done'));
    expect(await screen.findByText('Send the quote')).toBeTruthy();
    expect(callsTo(fetch, 'GET', '/api/todos/for/core.person/5?include_done=true')).toHaveLength(1);
  });

  it('adds a todo linked to the record and shows it', async () => {
    let added = false;
    const created = row(3, 'Ask for the invoice', { status: 'inbox' });
    const fetch = mockFetch({
      'GET /api/me': { body: ME },
      'GET /api/todos/filters': { body: filtersOf() },
      'GET /api/todos/projects': { body: [] },
      'POST /api/todos/items': { body: created },
    });
    // The list answers whatever has been added so far.
    const base = fetch.getMockImplementation()!;
    fetch.mockImplementation(async (input, init) => {
      if (input === '/api/todos/for/core.person/5') return new Response(JSON.stringify(added ? [created] : []));
      if (init?.method === 'POST') added = true;
      return base(input, init);
    });
    panel();
    expect(await screen.findByText('No open to-dos for this record.')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Add a todo'), { target: { value: 'Ask for the invoice' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(await screen.findByText('Ask for the invoice')).toBeTruthy();
    const [, init] = callsTo(fetch, 'POST', '/api/todos/items')[0];
    expect(JSON.parse(init!.body as string)).toMatchObject({
      title: 'Ask for the invoice', entity_type: 'core.person', entity_id: 5, status: 'inbox',
    });
  });

  it('completes through /complete, so a repeating todo spawns its next occurrence', async () => {
    const fetch = mockFetch({
      'GET /api/me': { body: ME },
      'GET /api/todos/for/core.person/5': { body: [OPEN] },
      'GET /api/todos/filters': { body: filtersOf() },
      'GET /api/todos/projects': { body: [] },
      'POST /api/todos/items/1/complete': { body: { ...OPEN, status: 'done' } },
    });
    panel();
    fireEvent.click(await screen.findByLabelText('Mark done'));
    await waitFor(() => expect(callsTo(fetch, 'POST', '/api/todos/items/1/complete')).toHaveLength(1));
  });
});
