import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { User } from '../api/types';
import { mockFetch } from '../../testing';
import { AuthProvider } from './AuthContext';
import { RequireAdmin, RequireAuth } from './guards';

const me = (role: User['role']): User => ({ id: 1, email: 'a@example.com', name: 'A', role, tz: 'UTC' });

function renderAs(role: User['role']) {
  mockFetch({ 'GET /api/me': { body: me(role) } });
  render(
    <MemoryRouter initialEntries={['/jobs']}>
      <AuthProvider>
        <Routes>
          {/* As in Root: the role is known before RequireAdmin decides. */}
          <Route path="/jobs" element={<RequireAuth><RequireAdmin><h1>Jobs</h1></RequireAdmin></RequireAuth>} />
          <Route path="/" element={<h1>Launcher</h1>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe('RequireAdmin', () => {
  it('shows an admin the page', async () => {
    renderAs('admin');
    expect(await screen.findByRole('heading', { name: 'Jobs' })).toBeTruthy();
  });

  it('tells a member they are not allowed, at the same URL, with a way home', async () => {
    renderAs('member');
    expect(await screen.findByRole('heading', { name: 'Not allowed' })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Jobs' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Launcher' })).toBeNull();
    expect(screen.getByRole('link', { name: 'Back to the launcher' }).getAttribute('href')).toBe('/');
  });
});
