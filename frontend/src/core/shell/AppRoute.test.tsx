import { render, screen } from '@testing-library/react';
import type { ComponentType, LazyExoticComponent } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { User } from '../api/types';
import type { RegisteredApp } from '../apps/registry';
import type { AppManifest } from '../apps/types';
import { AuthProvider } from '../auth/AuthContext';
import { mockFetch } from '../../testing';
import { AppRoute } from './AppRoute';
import { MemoryRouter } from 'react-router';

const member: User = { id: 2, email: 'm@example.com', name: 'M', role: 'member', tz: 'UTC' };
const app = (roles: AppManifest['roles']) => ({
  slug: 'x',
  manifest: { slug: 'x', roles } as AppManifest,
  contributions: { slug: 'x' },
  Screen: (() => <p>APP SCREEN</p>) as unknown as LazyExoticComponent<ComponentType>,
}) satisfies RegisteredApp;

function renderRoute(a: RegisteredApp, apps: unknown[]) {
  mockFetch({ 'GET /api/me': { body: member }, 'GET /api/core/apps': { body: apps } });
  render(<MemoryRouter><AuthProvider><AppRoute app={a} /></AuthProvider></MemoryRouter>);
}

afterEach(() => vi.unstubAllGlobals());

describe('AppRoute', () => {
  it("opens an app by URL for a role the manifest lists, even when it's hidden from the member", async () => {
    // Members are not sent hidden apps, so an empty app list must not 404 the route.
    renderRoute(app(['admin', 'member']), []);
    expect(await screen.findByText('APP SCREEN')).toBeTruthy();
  });

  it('404s for a role the manifest does not list', async () => {
    renderRoute(app(['admin']), []);
    expect(await screen.findByText('Page not found')).toBeTruthy();
    expect(screen.queryByText('APP SCREEN')).toBeNull();
  });
});
