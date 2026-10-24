import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CoreApp, User } from '../api/types';
import { CoreAppsProvider } from '../apps/CoreAppsContext';
import { AuthProvider } from '../auth/AuthContext';
import { callsTo, mockFetch } from '../../testing';
import { AppsCard } from './AppsCard';

const user = (role: User['role']): User => ({ id: 1, email: 'a@example.com', name: 'A', role, tz: 'UTC' });
const app = (slug: string, extra: Partial<CoreApp> = {}): CoreApp => ({
  slug, name: slug[0].toUpperCase() + slug.slice(1), description: '', path: `/${slug}`, icon: 'flask',
  roles: ['admin', 'member'], order: 1, badge: null, hidden: false, settings_cards: [], version: '0.1.0', ...extra,
});
const todos = app('todos', { badge: '/api/todos/badge' });
const example = app('example');

function renderCard(role: User['role'], routes = {}) {
  const fetchMock = mockFetch({ 'GET /api/me': { body: user(role) }, 'GET /api/core/apps': { body: [todos, example] }, ...routes });
  render(<AuthProvider><CoreAppsProvider><AppsCard /></CoreAppsProvider></AuthProvider>);
  return fetchMock;
}

const names = () => screen.getAllByRole('listitem').map(li => li.textContent);

afterEach(() => vi.unstubAllGlobals());

describe('AppsCard', () => {
  it('moves an app up: PUTs the whole new order, shows the answer and reloads the shared list', async () => {
    const fetchMock = renderCard('admin', { 'PUT /api/core/apps/order': { body: [example, todos] } });
    expect((await screen.findByRole('button', { name: 'Move Todos up' })).hasAttribute('disabled')).toBe(true);
    expect(screen.getByRole('button', { name: 'Move Example down' }).hasAttribute('disabled')).toBe(true);
    expect(names()[0]).toContain('Todos');

    fireEvent.click(screen.getByRole('button', { name: 'Move Example up' }));
    await waitFor(() => expect(names()[0]).toContain('Example'));
    const [put] = callsTo(fetchMock, 'PUT', '/api/core/apps/order');
    expect(JSON.parse(String(put[1]?.body))).toEqual({ slugs: ['example', 'todos'] });
    await waitFor(() => expect(callsTo(fetchMock, 'GET', '/api/core/apps')).toHaveLength(2));
  });

  it('hides an app with a PATCH and marks it hidden', async () => {
    const fetchMock = renderCard('admin', { 'PATCH /api/core/apps/example': { body: [todos, { ...example, hidden: true }] } });
    fireEvent.click(await screen.findByRole('button', { name: 'Hide Example' }));
    expect(await screen.findByRole('button', { name: 'Show Example' })).toBeTruthy();
    expect(names()[1]).toContain('Hidden');
    expect(JSON.parse(String(callsTo(fetchMock, 'PATCH', '/api/core/apps/example')[0][1]?.body))).toEqual({ hidden: true });
  });

  it('shows members the list without controls, and marks badge routes', async () => {
    const fetchMock = renderCard('member');
    await screen.findByText('Example');
    await waitFor(() => expect(callsTo(fetchMock, 'GET', '/api/me')).toHaveLength(1));
    await act(async () => {}); // let the role land before asserting its absence of controls
    expect(names()[0]).toContain('Badge');
    expect(screen.queryByRole('button')).toBeNull();
  });
});
