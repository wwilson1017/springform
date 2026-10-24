import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { TimelineEntry } from '../api/types';
import { callsTo, mockFetch } from '../../testing';
import { activeMentionQuery, applyMention, bodySegments, mentionMarkup } from './mentions';
import { NoteComposer } from './NoteComposer';
import { Timeline } from './Timeline';

afterEach(() => vi.unstubAllGlobals());

describe('mention helpers', () => {
  it('open a query only at the start or after whitespace, and not right after inserted markup', () => {
    expect(activeMentionQuery('hi @ad', 6)).toEqual({ start: 3, query: 'ad' });
    expect(activeMentionQuery('@', 1)).toEqual({ start: 0, query: '' });
    expect(activeMentionQuery('ada@example.com', 15)).toBeNull();
    expect(activeMentionQuery('hi @ad x', 8)).toBeNull();
    expect(activeMentionQuery('@[Ada](user:1)', 14)).toBeNull();
  });

  it('write the markup the server parses, dropping characters it cannot carry', () => {
    expect(mentionMarkup({ id: 7, name: 'Ada [ops]' })).toBe('@[Ada ops](user:7)');
    expect(applyMention('ping @ad please', 5, 8, '@[Ada](user:7)')).toEqual({ text: 'ping @[Ada](user:7)  please', caret: 20 });
  });

  it('split a body into text and mentions', () => {
    expect(bodySegments('Hey @[Ada Admin](user:1), see @[Max](user:2)')).toEqual([
      'Hey ', { id: 1, name: 'Ada Admin' }, ', see ', { id: 2, name: 'Max' },
    ]);
    expect(bodySegments('plain')).toEqual(['plain']);
  });
});

describe('MentionPicker in NoteComposer', () => {
  it('lists teammates for the typed query and inserts the markup on Enter', async () => {
    const fetchMock = mockFetch({
      'GET /api/core/timeline/mentionable?q=ma': { body: [{ id: 2, name: 'Max Member' }, { id: 3, name: 'Mara' }] },
    });
    render(<NoteComposer entityType="example.widget" entityId={7} onPosted={() => {}} />);
    const box = screen.getByLabelText('Add a note') as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: 'ask @ma', selectionStart: 7, selectionEnd: 7 } });
    expect(await screen.findByRole('option', { name: 'Max Member' })).toBeTruthy();
    expect(callsTo(fetchMock, 'GET', '/api/core/timeline/mentionable?q=ma')).toHaveLength(1);

    fireEvent.keyDown(box, { key: 'ArrowDown' });
    expect(screen.getByRole('option', { name: 'Mara' }).getAttribute('aria-selected')).toBe('true');
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(box.value).toBe('ask @[Mara](user:3) ');
    expect(screen.queryByRole('listbox')).toBeNull();
  });
});

describe('Timeline mention chips', () => {
  it('render a mention as @Name, not as markup', async () => {
    const entry: TimelineEntry = { id: 1, kind: 'note', body: 'Over to @[Max Member](user:2)', changes: null, author: { id: 1, name: 'Ada' }, created_at: '2026-10-20T15:00:00Z' };
    mockFetch({ 'GET /api/core/timeline?entity_type=example.widget&entity_id=7&limit=50': { body: [entry] } });
    render(<Timeline entityType="example.widget" entityId={7} />);
    expect((await screen.findByText('@Max Member')).getAttribute('title')).toBe('Mentioned Max Member');
    expect(screen.queryByText(/user:2/)).toBeNull();
  });
});
