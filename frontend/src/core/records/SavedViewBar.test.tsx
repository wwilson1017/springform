import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { getToasts } from '../../shared/toast';
import { callsTo, mockFetch } from '../../testing';
import { isStaleView, viewPayload, viewValue } from './savedViews';
import { SavedViewBar } from './SavedViewBar';
import type { SavedView } from './types';

const LIST = '/api/core/views?surface=core.reminders';
const view = (id: number, name: string, payload: Record<string, unknown>, extra: Partial<SavedView> = {}): SavedView => ({
  id, surface: 'core.reminders', entity_type: null, name, version: 3, payload, owner: { id: 1, name: 'Ada' },
  is_shared: false, can_edit: true, created_at: '2026-10-20T15:00:00Z', updated_at: '2026-10-20T15:00:00Z', ...extra,
});
const fresh = view(1, 'Open this week', viewPayload({ status: 'open' }, 2));
const old = view(2, 'Old layout', viewPayload({ state: 'open' }, 1));

afterEach(() => vi.unstubAllGlobals());

function renderBar(routes: Parameters<typeof mockFetch>[0] = {}) {
  const onChange = vi.fn();
  const fetchMock = mockFetch({ [`GET ${LIST}`]: { body: [fresh, old] }, ...routes });
  render(<SavedViewBar surface="core.reminders" value={{ status: 'done' }} onChange={onChange} schemaVersion={2} />);
  fireEvent.click(screen.getByRole('button', { name: 'Saved views' }));
  return { fetchMock, onChange };
}

describe('saved view payloads', () => {
  it('carry the screen schema version and refuse a mismatch', () => {
    expect(viewPayload({ a: 1 }, 2)).toEqual({ schema_version: 2, value: { a: 1 } });
    expect(viewValue(fresh, 2)).toEqual({ status: 'open' });
    expect(isStaleView(old, 2)).toBe(true);
    expect(viewValue(old, 2)).toBeNull();
    // A payload written by something else entirely is stale too, never applied.
    expect(isStaleView({ payload: { status: 'open' } }, 2)).toBe(true);
  });
});

describe('SavedViewBar', () => {
  it('applies a current view and shows a stale one disabled, with the reason', async () => {
    const { onChange } = renderBar();
    const stale = await screen.findByRole('button', { name: 'Old layout' });
    expect((stale as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/older version of this screen/)).toBeTruthy();
    fireEvent.click(stale);
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Open this week' }));
    expect(onChange).toHaveBeenCalledWith({ status: 'open' });
    expect(screen.getByRole('button', { name: /View: Open this week/ })).toBeTruthy();
  });

  it('saves the current value under the schema version', async () => {
    const { fetchMock } = renderBar({ 'POST /api/core/views': { body: view(3, 'Done', viewPayload({ status: 'done' }, 2)) } });
    fireEvent.click(await screen.findByRole('button', { name: 'Save current view as…' }));
    fireEvent.change(screen.getByLabelText('View name'), { target: { value: ' Done ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/core/views')).toHaveLength(1));
    const [, init] = callsTo(fetchMock, 'POST', '/api/core/views')[0];
    expect(JSON.parse(init!.body as string)).toEqual({ surface: 'core.reminders', name: 'Done', payload: { schema_version: 2, value: { status: 'done' } } });
  });

  it('sends the server version with an edit and, on 409 stale_view, reloads the list and says so', async () => {
    const { fetchMock } = renderBar({ 'PATCH /api/core/views/1': { status: 409, body: { detail: 'stale_view' } } });
    fireEvent.click((await screen.findAllByRole('button', { name: 'Rename' }))[0]);
    fireEvent.change(screen.getByLabelText('View name'), { target: { value: 'Renamed' } });
    fireEvent.submit(screen.getByLabelText('View name').closest('form')!);

    await vi.waitFor(() => expect(callsTo(fetchMock, 'GET', LIST)).toHaveLength(2));
    const [, init] = callsTo(fetchMock, 'PATCH', '/api/core/views/1')[0];
    expect(JSON.parse(init!.body as string)).toEqual({ version: 3, name: 'Renamed' });
    expect(getToasts().at(-1)?.message).toMatch(/changed somewhere else/);
    expect(screen.queryByLabelText('View name')).toBeNull();
  });

  it('shows a name conflict in the form rather than as a toast', async () => {
    renderBar({ 'POST /api/core/views': { status: 409, body: { detail: 'duplicate_name' } } });
    fireEvent.click(await screen.findByRole('button', { name: 'Save current view as…' }));
    fireEvent.change(screen.getByLabelText('View name'), { target: { value: 'Open this week' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect((await screen.findByRole('alert')).textContent).toBe('You already have a view with that name.');
  });
});
