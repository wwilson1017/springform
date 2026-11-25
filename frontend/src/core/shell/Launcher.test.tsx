import { act, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CoreApp, User } from '../api/types';
import { CoreAppsProvider } from '../apps/CoreAppsContext';
import { AuthProvider } from '../auth/AuthContext';
import { callsTo, mockFetch } from '../../testing';
import { Launcher } from './Launcher';

const user = (role: User['role']): User => ({ id: 1, email: 'a@example.com', name: 'A', role, tz: 'UTC' });
const app = (slug: string, extra: Partial<CoreApp> = {}): CoreApp => ({
  slug,
  name: slug[0].toUpperCase() + slug.slice(1),
  description: `${slug} app`,
  path: `/${slug}`,
  icon: 'flask',
  roles: ['admin', 'member'],
  order: 1,
  badge: null,
  hidden: false,
  folder: null,
  settings_cards: [],
  version: '0.1.0',
  ...extra,
});

function renderLauncher(role: User['role'], apps: CoreApp[], extra = {}, at = '/') {
  const fetchMock = mockFetch({ 'GET /api/me': { body: user(role) }, 'GET /api/core/apps': { body: apps }, ...extra });
  render(
    <MemoryRouter initialEntries={[at]}>
      <AuthProvider>
        <CoreAppsProvider>
          <Launcher />
        </CoreAppsProvider>
      </AuthProvider>
    </MemoryRouter>,
  );
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
    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });
    expect(badgeCalls()).toBe(1);

    await act(async () => {
      setVisibility('visible');
    });
    expect(badgeCalls()).toBe(2);
    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });
    expect(badgeCalls()).toBe(3);
  });
});

describe('Launcher stars', () => {
  const ten = Array.from({ length: 10 }, (_, i) => app(`app${i}`));
  const appOrder = () => screen.getAllByRole('link').map((a) => a.getAttribute('aria-label'));

  afterEach(() => localStorage.clear());

  it('shows no stars on a board under 10 tiles, and ignores saved ones', async () => {
    localStorage.setItem('springform.launcher.starred.1', '["beta"]');
    renderLauncher('admin', [app('alpha'), app('beta')]);
    await screen.findByRole('link', { name: 'Alpha' });
    expect(screen.queryByRole('button', { name: /star/i })).toBeNull();
    expect(appOrder()).toEqual(['Alpha', 'Beta']);
  });

  it('moves a starred app to the top and remembers it per user', async () => {
    renderLauncher('admin', ten);
    await screen.findByRole('link', { name: 'App0' });
    expect(appOrder()[0]).toBe('App0');
    act(() => screen.getByRole('button', { name: 'Star App7' }).click());
    expect(appOrder().slice(0, 2)).toEqual(['App7', 'App0']);
    expect(screen.getByRole('button', { name: 'Unstar App7' }).getAttribute('aria-pressed')).toBe('true');
    expect(localStorage.getItem('springform.launcher.starred.1')).toBe('["app7"]');
    act(() => screen.getByRole('button', { name: 'Unstar App7' }).click());
    expect(appOrder().slice(0, 2)).toEqual(['App0', 'App1']);
  });
});

describe('Launcher folders', () => {
  const filed = [
    app('alpha'),
    app('sales', { folder: 'Dashboards' }),
    app('beta'),
    app('ops', { folder: 'Dashboards' }),
  ];
  const labels = () => screen.getAllByRole('link').map((a) => a.getAttribute('aria-label'));

  it('shows one folder tile where its first app falls, with the badges added up', async () => {
    renderLauncher(
      'admin',
      filed.map((a) => (a.folder ? { ...a, badge: `/api/${a.slug}/badge` } : a)),
      {
        'GET /api/sales/badge': { body: { count: 2 } },
        'GET /api/ops/badge': { body: { count: 1 } },
      },
    );
    await screen.findByRole('link', { name: 'Alpha' });
    expect(labels()).toEqual(['Alpha', 'Dashboards folder', 'Beta']);
    const folder = screen.getByRole('link', { name: 'Dashboards folder' });
    expect(folder.getAttribute('href')).toBe('/?folder=Dashboards');
    await waitFor(() => expect(folder.textContent).toContain('3'));
  });

  it('opens a folder from the URL, showing only its apps and a way back', async () => {
    renderLauncher('admin', filed, {}, '/?folder=Dashboards');
    await screen.findByRole('link', { name: 'Sales' });
    expect(screen.getByRole('heading', { name: 'Dashboards' })).toBeTruthy();
    expect(labels()).toEqual([null, 'Sales', 'Ops']); // the ← Apps link has no aria-label
    expect(screen.getByRole('link', { name: '← Apps' }).getAttribute('href')).toBe('/');
  });

  it('shows a starred app at the top level as well as in its folder', async () => {
    localStorage.setItem('springform.launcher.starred.1', '["ops"]');
    const many = [...filed, ...Array.from({ length: 6 }, (_, i) => app(`app${i}`))];
    renderLauncher('admin', many);
    await screen.findByRole('link', { name: 'Ops' });
    expect(labels().slice(0, 3)).toEqual(['Ops', 'Alpha', 'Dashboards folder']);
    localStorage.clear();
  });
});

describe('Launcher link tiles', () => {
  it('shows link tiles after the apps, opening in a new tab, with hidden ones marked for admins', async () => {
    renderLauncher('admin', [app('example')], {
      'GET /api/core/launcher/links': {
        body: [
          { id: 1, title: 'Todo', url: 'https://todo.example.test', icon: 'check-square', hidden: false },
          { id: 2, title: 'Notes', url: 'https://notes.example.test', icon: 'file', hidden: true },
        ],
      },
    });
    const todo = await screen.findByRole('link', { name: 'Todo (opens in a new tab)' });
    expect(todo.getAttribute('href')).toBe('https://todo.example.test');
    expect(todo.getAttribute('target')).toBe('_blank');
    expect(todo.getAttribute('rel')).toBe('noopener noreferrer');
    const links = screen.getAllByRole('link').map((a) => a.getAttribute('aria-label'));
    expect(links).toEqual(['Example', 'Todo (opens in a new tab)', 'Notes (opens in a new tab)']);
    expect(screen.getByRole('link', { name: 'Notes (opens in a new tab)' }).textContent).toContain('hidden');
  });
});
