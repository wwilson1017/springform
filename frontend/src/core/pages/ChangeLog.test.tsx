import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, mockFetch, type Reply } from '../../testing';
import type { User } from '../api/types';
import { CoreAppsProvider } from '../apps/CoreAppsContext';
import { AuthProvider } from '../auth/AuthContext';
import { ChangeLogPage } from './ChangeLog';
import type { ChangeRow } from './types';

const user = (role: User['role']): User => ({ id: 1, email: 'a@example.com', name: 'A', role, tz: 'UTC' });
const exampleApp = {
  slug: 'example', name: 'Example', description: '', path: '/example', icon: 'flask', roles: ['admin', 'member'],
  order: 1, badge: null, hidden: false, settings_cards: [], version: '0.1.0',
};
const row = (id: number, extra: Partial<ChangeRow> = {}): ChangeRow => ({
  id, at: '2026-10-24T03:43:00Z', user: { id: 2, name: 'Pat' }, app: 'example', entity_type: 'example.widget',
  entity_id: 3, title: 'Blue crate', url: '/example/3', field: 'name', old: 'Old', new: `New ${id}`, reason: null,
  deleted_at: null, ...extra,
});

function renderAt(url: string, role: User['role'], routes: Record<string, Reply>) {
  const fetchMock = mockFetch({
    'GET /api/me': { body: user(role) }, 'GET /api/core/apps': { body: [exampleApp] }, 'GET /api/auth/users': { body: [] }, ...routes,
  });
  render(<MemoryRouter initialEntries={[url]}><AuthProvider><CoreAppsProvider><ChangeLogPage /></CoreAppsProvider></AuthProvider></MemoryRouter>);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe('ChangeLogPage', () => {
  it('reads its filters from the query string, so a record page can deep-link, and pages back with before=', async () => {
    const base = '/api/core/changelog?entity_type=example.widget&entity_id=3&limit=1';
    renderAt('/changelog?entity_type=example.widget&entity_id=3&limit=1&unrelated=x', 'admin', {
      [`GET ${base}`]: { body: [row(9)] },
      [`GET ${base}&before=9`]: { body: [row(5)] },
      [`GET ${base}&before=5`]: { body: [] },
    });
    expect(await screen.findByText('New 9')).toBeTruthy();
    expect((screen.getByLabelText('Record type') as HTMLInputElement).value).toBe('example.widget');
    expect((screen.getByLabelText('Record id') as HTMLInputElement).value).toBe('3');

    fireEvent.click(screen.getByRole('button', { name: 'Show older' }));
    expect(await screen.findByText('New 5')).toBeTruthy();
    expect(screen.getByText('New 9')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Show older' }));
    expect(await screen.findByText("That's the oldest change for these filters.")).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Show older' })).toBeNull();
  });

  it('applies a picked filter through the URL; a member picks users from the rows, never the admin user list', async () => {
    const fetchMock = renderAt('/changelog', 'member', {
      'GET /api/core/changelog?limit=50': { body: [row(2)] },
      'GET /api/core/changelog?app=example&limit=50': { body: [row(1, { new: 'Filtered' })] },
    });
    await screen.findByText('New 2');
    expect(screen.getByRole('option', { name: 'Pat' })).toBeTruthy();

    fireEvent.change(screen.getByLabelText('App'), { target: { value: 'example' } });
    expect(await screen.findByText('Filtered')).toBeTruthy();
    expect(callsTo(fetchMock, 'GET', '/api/auth/users')).toHaveLength(0);
  });

  it('marks a row about a deleted record and does not link it', async () => {
    renderAt('/changelog', 'admin', {
      'GET /api/core/changelog?limit=50': { body: [row(4, { title: null, url: null, deleted_at: '2026-10-24T04:00:00Z' })] },
    });
    expect(await screen.findByText('deleted')).toBeTruthy();
    expect(screen.getByText('example.widget #3').tagName).toBe('SPAN');
  });
});
