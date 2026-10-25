import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { TimelineEntry } from '../api/types';
import { callsTo, mockFetch } from '../../testing';
import { recordChanged } from './recordEvents';
import { Timeline } from './Timeline';

const BASE = '/api/core/timeline?entity_type=example.widget&entity_id=7';
const LIST = `${BASE}&limit=50`;
const entries: TimelineEntry[] = [
  { id: 2, kind: 'field_change', body: '', changes: [{ field: 'color', old: 'red', new: 'blue' }, { field: 'is_private', old: false, new: true }], author: { id: 1, name: 'Ada' }, created_at: '2026-10-20T15:04:05Z' },
  { id: 1, kind: 'note', body: 'First note', changes: null, author: { id: 1, name: 'Ada' }, created_at: '2026-10-20T15:00:00Z' },
];

afterEach(() => vi.unstubAllGlobals());

describe('Timeline', () => {
  it('renders a field change as "X changed from A to B"', async () => {
    const fetchMock = mockFetch({ [`GET ${LIST}`]: { body: entries } });
    render(<Timeline entityType="example.widget" entityId={7} />);
    expect(await screen.findByText('Color changed from red to blue')).toBeTruthy();
    expect(screen.getByText('Is private changed from no to yes')).toBeTruthy();
    expect(screen.getByText('First note')).toBeTruthy();
    // No custom field among the changes: no definitions fetch.
    expect(fetchMock.mock.calls.filter(([url]) => String(url).startsWith('/api/core/fields/'))).toHaveLength(0);
  });

  it("names a custom field change by the field's label, fetched once per entity type", async () => {
    const custom: TimelineEntry = { ...entries[0], id: 5, changes: [{ field: 'field.favourite_cake', old: null, new: 'Lemon' }] };
    const defs = '/api/core/fields/definitions?entity_type=core.person&include_archived=true';
    const fetchMock = mockFetch({
      'GET /api/core/timeline?entity_type=core.person&entity_id=1&limit=50': { body: [custom] },
      'GET /api/core/timeline?entity_type=core.person&entity_id=2&limit=50': { body: [custom] },
      [`GET ${defs}`]: { body: [{ id: 1, entity_type: 'core.person', key: 'favourite_cake', label: 'Favourite cake', type: 'text',
        options: null, required: false, position: 0, archived_at: null }] },
    });
    render(<><Timeline entityType="core.person" entityId={1} /><Timeline entityType="core.person" entityId={2} /></>);
    expect(await screen.findAllByText('Favourite cake changed from empty to Lemon')).toHaveLength(2);
    expect(callsTo(fetchMock, 'GET', defs)).toHaveLength(1);
  });

  it("refetches when this record's custom fields are saved, and only this record's", async () => {
    const fetchMock = mockFetch({ [`GET ${LIST}`]: { body: [entries[1]] } });
    render(<Timeline entityType="example.widget" entityId={7} />);
    await screen.findByText('First note');
    act(() => recordChanged('example.widget', 8));
    act(() => recordChanged('core.person', 7));
    expect(callsTo(fetchMock, 'GET', LIST)).toHaveLength(1);
    act(() => recordChanged('example.widget', 7));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'GET', LIST)).toHaveLength(2));
  });

  it('posts a note for this record and reloads the list', async () => {
    const fetchMock = mockFetch({
      [`GET ${LIST}`]: { body: [] },
      'POST /api/core/timeline': { body: { ...entries[1], id: 3, body: 'Called them' } },
    });
    render(<Timeline entityType="example.widget" entityId={7} />);
    expect(await screen.findByText('No activity yet.')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Add a note'), { target: { value: '  Called them ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add note' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'GET', LIST)).toHaveLength(2));
    const [, init] = callsTo(fetchMock, 'POST', '/api/core/timeline')[0];
    expect(JSON.parse(init!.body as string)).toEqual({ entity_type: 'example.widget', entity_id: 7, body: 'Called them' });
    expect((screen.getByLabelText('Add a note') as HTMLTextAreaElement).value).toBe('');
  });

  it('pages older entries with before=<last id> while full pages keep coming', async () => {
    const note = (id: number): TimelineEntry => ({ ...entries[1], id, body: `note ${id}` });
    const firstPage = Array.from({ length: 50 }, (_, i) => note(120 - i)); // 120 … 71
    const fetchMock = mockFetch({
      [`GET ${LIST}`]: { body: firstPage },
      [`GET ${BASE}&before=71&limit=50`]: { body: [note(70), note(69)] },
    });
    render(<Timeline entityType="example.widget" entityId={7} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Show older' }));
    expect(await screen.findByText('note 69')).toBeTruthy();
    expect(callsTo(fetchMock, 'GET', `${BASE}&before=71&limit=50`)).toHaveLength(1);
    // A short page means there is nothing older.
    expect(screen.queryByRole('button', { name: 'Show older' })).toBeNull();
  });
});
