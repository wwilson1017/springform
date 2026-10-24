import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { TimelineEntry } from '../api/types';
import { callsTo, mockFetch } from '../../testing';
import { Timeline } from './Timeline';

const BASE = '/api/core/timeline?entity_type=example.widget&entity_id=7';
const LIST = `${BASE}&limit=50`;
const entries: TimelineEntry[] = [
  { id: 2, kind: 'field_change', body: null, changes: [{ field: 'color', old: 'red', new: 'blue' }, { field: 'is_private', old: false, new: true }], author: { id: 1, name: 'Ada' }, created_at: '2026-10-20T15:04:05Z' },
  { id: 1, kind: 'note', body: 'First note', changes: null, author: { id: 1, name: 'Ada' }, created_at: '2026-10-20T15:00:00Z' },
];

afterEach(() => vi.unstubAllGlobals());

describe('Timeline', () => {
  it('renders a field change as "changed X from A to B"', async () => {
    mockFetch({ [`GET ${LIST}`]: { body: entries } });
    render(<Timeline entityType="example.widget" entityId={7} />);
    expect(await screen.findByText('changed color from red to blue')).toBeTruthy();
    expect(screen.getByText('changed is private from no to yes')).toBeTruthy();
    expect(screen.getByText('First note')).toBeTruthy();
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
