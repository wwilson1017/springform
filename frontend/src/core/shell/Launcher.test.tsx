import { act, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CoreApp, User } from '../api/types';
import { CoreAppsProvider } from '../apps/CoreAppsContext';
import { AuthProvider } from '../auth/AuthContext';
import { callsTo, mockFetch } from '../../testing';
import { Launcher } from './Launcher';

const user = (role: User['role']): User => ({ id: 1, email: 'a@example.com', name: 'A', role, tz: 'UTC' });
const app = (slug: string, extra: Partial<CoreApp> = {}): CoreApp => ({
  slug, name: slug[0].toUpperCase() + slug.slice(1), description: `${slug} app`, path: `/${slug}`, icon: 'flask',
  roles: ['admin', 'member'], order: 1, badge: null, hidden: false, settings_cards: [], version: '0.1.0', ...extra,
});

function renderLauncher(role: User['role'], apps: CoreApp[], extra = {}) {
  const fetchMock = mockFetch({ 'GET /api/me': { body: user(role) }, 'GET /api/core/apps': { body: apps }, ...extra });
  render(<MemoryRouter><AuthProvider><CoreAppsProvider><Launcher /></CoreAppsProvider></AuthProvider></MemoryRouter>);
  return fetchMock;
}

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
  document.dispatchEvent(new Event('visibilitychange'));
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  setVisibility('visible');
});

describe('Launcher', () => {
  it('shows a member only the tiles for their role, with no hidden apps', async () => {
    // The server filters by role; the launcher must not show an admin-only app even if it leaks.
    renderLauncher('member', [app('example'), app('payroll', { roles: ['admin'] })]);
    expect(await screen.findByRole('link', { name: 'Example' })).toBeTruthy();
    expect(screen.queryByRole('link', { name: 'Payroll' })).toBeNull();
    expect(screen.queryByText('hidden')).toBeNull();
  });

  it('shows admins hidden apps, marked hidden', async () => {
    renderLauncher('admin', [app('example'), app('archive', { hidden: true })]);
    const tile = await screen.findByRole('link', { name: 'Archive' });
    expect(tile.textContent).toContain('hidden');
    expect(screen.getByRole('link', { name: 'Example' }).textContent).not.toContain('hidden');
  });

  it('polls badges every 60 s, but only while the tab is visible', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    const fetchMock = renderLauncher('admin', [app('example', { badge: '/api/example/badge' })], {
      'GET /api/example/badge': { body: { count: 3, label: '3 new widgets' } },
    });
    expect((await screen.findByLabelText('3 new widgets')).textContent).toBe('3');
    const badgeCalls = () => callsTo(fetchMock, 'GET', '/api/example/badge').length;
    expect(badgeCalls()).toBe(1);

    setVisibility('hidden');
    await act(async () => { vi.advanceTimersByTime(60_000); });
    expect(badgeCalls()).toBe(1);

    await act(async () => { setVisibility('visible'); });
    expect(badgeCalls()).toBe(2);
    await act(async () => { vi.advanceTimersByTime(60_000); });
    expect(badgeCalls()).toBe(3);
  });
});
