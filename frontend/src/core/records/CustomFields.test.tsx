import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, mockFetch } from '../../testing';
import { resetUserNames } from '../../shared/users';
import { CustomFields } from './CustomFields';
import { fromDraft, toDraft } from './fieldValues';
import { onRecordChanged } from './recordEvents';
import type { FieldDefinition, FieldType } from './types';

const DEFS = '/api/core/fields/definitions?entity_type=example.widget';
const VALUES = '/api/core/fields/values?entity_type=example.widget&entity_id=7';
const USERS = '/api/core/timeline/mentionable?q=';

let nextId = 1;
const def = (key: string, type: FieldType, extra: Partial<FieldDefinition> = {}): FieldDefinition => ({
  id: nextId++, entity_type: 'example.widget', key, label: key.replace(/_/g, ' '), type, options: null,
  required: false, position: nextId * 10, archived_at: null, ...extra,
});
const ALL = [
  def('notes', 'text', { required: true }), def('size', 'number'), def('fragile', 'boolean'), def('ships_on', 'date'),
  def('tier', 'select', { options: ['Gold', 'Silver'] }), def('tags', 'multiselect', { options: ['a', 'b', 'c'] }),
  def('site', 'url'), def('rep', 'user'),
];
const STORED = { notes: 'Handle with care', size: 2.5, fragile: true, ships_on: '2026-11-02', tier: 'Gold', tags: ['a', 'c'], site: 'https://example.com', rep: 2 };

afterEach(() => {
  vi.unstubAllGlobals();
  resetUserNames();
});

function renderAll(values: Record<string, unknown> = STORED, put: { status?: number; body?: unknown } = { body: STORED }) {
  const fetchMock = mockFetch({
    [`GET ${DEFS}`]: { body: ALL },
    [`GET ${VALUES}`]: { body: values },
    [`GET ${USERS}`]: { body: [{ id: 1, name: 'Ada Admin' }, { id: 2, name: 'Max Member' }] },
    'PUT /api/core/fields/values': put,
  });
  render(<CustomFields entityType="example.widget" entityId={7} />);
  return fetchMock;
}

describe('CustomFields', () => {
  it('shows one value per field, read by its type', async () => {
    renderAll();
    await screen.findByText('Handle with care');
    const dl = screen.getByRole('region', { name: 'Custom fields' });
    for (const text of ['notes *', 'Handle with care', '2.5', 'Yes', '2026-11-02', 'Gold', 'a, c', 'https://example.com']) {
      expect(within(dl).getByText(text)).toBeTruthy();
    }
    expect(await within(dl).findByText('Max Member')).toBeTruthy();
    expect(within(dl).getByRole('link', { name: 'https://example.com' }).getAttribute('href')).toBe('https://example.com');
  });

  it('renders the editor each type needs and PUTs only what changed, typed, in one request', async () => {
    const fetchMock = renderAll({ notes: 'Handle with care', tier: 'Gold', tags: ['a'] });
    const changed = vi.fn();
    const unsubscribe = onRecordChanged(changed);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    expect((screen.getByLabelText('size') as HTMLInputElement).type).toBe('number');
    expect((screen.getByLabelText('ships on') as HTMLInputElement).type).toBe('date');
    expect((screen.getByLabelText('site') as HTMLInputElement).type).toBe('url');
    expect(screen.getByLabelText('fragile').tagName).toBe('SELECT');
    expect(within(screen.getByRole('group', { name: 'tags' })).getAllByRole('checkbox')).toHaveLength(3);
    expect(screen.getByLabelText('rep').getAttribute('role')).toBe('combobox');

    fireEvent.change(screen.getByLabelText('size'), { target: { value: '12' } });
    fireEvent.change(screen.getByLabelText('fragile'), { target: { value: 'no' } });
    fireEvent.change(screen.getByLabelText('ships on'), { target: { value: '2026-12-01' } });
    fireEvent.click(within(screen.getByRole('group', { name: 'tags' })).getByLabelText('b'));
    fireEvent.focus(screen.getByLabelText('rep'));
    fireEvent.click(await screen.findByRole('option', { name: 'Max Member' }));
    fireEvent.change(screen.getByLabelText('tier'), { target: { value: '' } }); // clearing sends null
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await vi.waitFor(() => expect(callsTo(fetchMock, 'PUT', '/api/core/fields/values')).toHaveLength(1));
    const [, init] = callsTo(fetchMock, 'PUT', '/api/core/fields/values')[0];
    expect(JSON.parse(init!.body as string)).toEqual({
      entity_type: 'example.widget', entity_id: 7,
      values: { size: 12, fragile: false, ships_on: '2026-12-01', tags: ['a', 'b'], rep: 2, tier: null },
    });
    // The record's Timeline hears about the save, so the change entry shows.
    await vi.waitFor(() => expect(changed).toHaveBeenCalledWith('example.widget', 7));
    unsubscribe();
  });

  it('turns read-only when the server says the record is not writable', async () => {
    renderAll(STORED, { status: 403, body: { detail: 'forbidden' } });
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('notes *'), { target: { value: 'changed' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Handle with care')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
  });

  it('renders nothing when the entity type has no fields', async () => {
    const fetchMock = mockFetch({ [`GET ${DEFS}`]: { body: [] }, [`GET ${VALUES}`]: { body: {} } });
    const { container } = render(<CustomFields entityType="example.widget" entityId={7} />);
    await vi.waitFor(() => expect(callsTo(fetchMock, 'GET', VALUES)).toHaveLength(1));
    expect(container.innerHTML).toBe('');
  });
});

describe('field drafts', () => {
  it('round-trip every type, and empty means null', () => {
    for (const d of ALL) {
      const stored = STORED[d.key as keyof typeof STORED];
      expect(fromDraft(d, toDraft(d, stored))).toEqual(stored);
      expect(fromDraft(d, toDraft(d, null))).toBeNull();
    }
  });

  it('refuse a number that does not parse, and trim text (blank clears)', () => {
    expect(fromDraft(ALL[1], '1,5')).toEqual(new Error('size: expected a number'));
    expect(fromDraft(ALL[0], '  padded  ')).toBe('padded');
    expect(fromDraft(ALL[0], '   ')).toBeNull();
  });
});
