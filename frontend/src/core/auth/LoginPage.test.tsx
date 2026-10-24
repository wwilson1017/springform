import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AuthStatus } from '../api/types';
import { callsTo, mockFetch, type Reply } from '../../testing';
import { AuthProvider } from './AuthContext';
import { LoginPage } from './LoginPage';

const status = (s: Partial<AuthStatus>): Reply => ({ body: { setup_required: false, google: false, preview: false, ...s } });

function renderLogin(routes: Record<string, Reply>) {
  const fetchMock = mockFetch({ 'GET /api/me': { status: 401 }, ...routes });
  render(
    <MemoryRouter initialEntries={['/login']}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/setup" element={<p>SETUP</p>} />
          <Route path="/" element={<p>HOME</p>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
  return fetchMock;
}

// The API client reads the real address bar to tell a wrong password from an expired session.
beforeEach(() => window.history.pushState({}, '', '/login'));
afterEach(() => vi.unstubAllGlobals());

describe('LoginPage', () => {
  it('shows only the password form when Google and preview are off', async () => {
    const fetchMock = renderLogin({ 'GET /api/auth/status': status({}) });
    expect(await screen.findByLabelText('Email')).toBeTruthy();
    await vi.waitFor(() => expect(callsTo(fetchMock, 'GET', '/api/auth/status')).toHaveLength(1));
    expect(screen.queryByRole('button', { name: 'Continue with Google' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Member' })).toBeNull();
  });

  it('shows the Google button when enabled, as a form POST to the start route', async () => {
    renderLogin({ 'GET /api/auth/status': status({ google: true }) });
    const google = await screen.findByRole('button', { name: 'Continue with Google' });
    const form = google.closest('form')!;
    expect([form.getAttribute('method'), form.getAttribute('action')]).toEqual(['post', '/api/auth/google/start']);
    expect(screen.queryByRole('button', { name: 'Member' })).toBeNull();
  });

  it('shows the role picker only in preview, and signs in as the picked role', async () => {
    const fetchMock = renderLogin({
      'GET /api/auth/status': status({ preview: true }),
      'POST /api/auth/preview': { body: { user: {} } },
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Member' }));
    // After the cookie is set the page asks /api/me who that is; answer as the member now.
    mockFetch({ 'GET /api/me': { body: { id: 2, email: 'm@example.com', name: 'M', role: 'member', tz: 'UTC' } } });
    expect(await screen.findByText('HOME')).toBeTruthy();
    expect(JSON.parse(callsTo(fetchMock, 'POST', '/api/auth/preview')[0][1]!.body as string)).toEqual({ role: 'member' });
    expect(screen.queryByRole('button', { name: 'Continue with Google' })).toBeNull();
  });

  it('still offers the password form when the status check fails', async () => {
    renderLogin({ 'GET /api/auth/status': { status: 502 } });
    expect(await screen.findByText(/Can't reach the server right now/)).toBeTruthy();
    expect(screen.getByLabelText('Password')).toBeTruthy();
  });

  it('sends a fresh install to /setup', async () => {
    renderLogin({ 'GET /api/auth/status': status({ setup_required: true }) });
    expect(await screen.findByText('SETUP')).toBeTruthy();
  });

  it('explains a wrong password without leaving the page', async () => {
    renderLogin({ 'GET /api/auth/status': status({}), 'POST /api/auth/login': { status: 401, body: { detail: 'invalid_credentials' } } });
    fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'a@example.com' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'nope' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect((await screen.findByRole('alert')).textContent).toBe("That email and password don't match an account.");
  });
});
