import { act, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Workspace } from '../settings/types';
import { CoreAppsProvider } from '../apps/CoreAppsContext';
import { AuthProvider } from '../auth/AuthContext';
import { setWorkspace, workspaceTitle } from '../settings/useWorkspace';
import { mockFetch } from '../../testing';
import { Layout } from './Layout';

const workspace = (extra: Partial<Workspace> = {}): Workspace => ({
  name: 'Acme Bakery',
  show_name: true,
  timezone: 'UTC',
  version: '0.1.3',
  preview: false,
  public_url: '',
  ...extra,
});

function renderLayout() {
  // jsdom has no matchMedia; the header and the theme toggle ask it.
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  mockFetch({
    'GET /api/me': { body: { id: 1, email: 'a@example.com', name: 'A', role: 'admin', tz: 'UTC' } },
    'GET /api/core/apps': { body: [] },
  });
  render(
    <MemoryRouter>
      <AuthProvider>
        <CoreAppsProvider>
          <Layout />
        </CoreAppsProvider>
      </AuthProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the header name beside the logo', () => {
  it('shows the name as text by default, with decorative logos', () => {
    act(() => setWorkspace(workspace()));
    renderLayout();
    const home = screen.getByRole('link', { name: 'Acme Bakery' });
    expect(home.textContent).toBe('Acme Bakery');
    expect(home.hasAttribute('aria-label')).toBe(false);
    for (const img of home.querySelectorAll('img')) expect(img.getAttribute('alt')).toBe('');
  });

  it('hides the text when turned off, and the link keeps the name as its label', () => {
    act(() => setWorkspace(workspace({ show_name: false })));
    renderLayout();
    const home = screen.getByRole('link', { name: 'Acme Bakery' });
    expect(home.textContent).toBe('');
    expect(home.getAttribute('aria-label')).toBe('Acme Bakery');
  });
});

describe('the tab title', () => {
  it('follows the install name, but not over a title a page set itself', () => {
    act(() => setWorkspace(workspace({ name: 'First' })));
    act(() => setWorkspace(workspace({ name: 'Renamed' })));
    expect(document.title).toBe('Renamed');
    document.title = 'Todos';
    act(() => setWorkspace(workspace({ name: 'Again' })));
    expect(document.title).toBe('Todos');
    // Leaving that page restores the install name it loaded meanwhile, not the title it found.
    expect(workspaceTitle()).toBe('Again');
  });
});
