import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { User } from '../api/types';
import { callsTo, mockFetch, type Reply } from '../../testing';
import { AuthProvider } from './AuthContext';
import InvitePage from './InvitePage';
import ResetPasswordPage from './ResetPasswordPage';

const invitee: User = { id: 7, email: 'new@example.com', name: 'New Person', role: 'member', tz: 'UTC' };
const INVITE = 'GET /api/auth/invite/tok-1';

function renderAt(entry: string, routes: Record<string, Reply>) {
  // The API client reads the real address bar: on these pages a 401 is an answer.
  window.history.pushState({}, '', entry.split('?')[0]);
  const fetchMock = mockFetch({ 'GET /api/me': { status: 401 }, ...routes });
  render(
    <MemoryRouter initialEntries={[entry]}>
      <AuthProvider>
        <Routes>
          <Route path="/invite/:token" element={<InvitePage />} />
          <Route path="/reset-password/:token" element={<ResetPasswordPage />} />
          <Route path="/login" element={<p>LOGIN</p>} />
          <Route path="/" element={<p>HOME</p>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
  return fetchMock;
}

function fillPasswords(first: string, second: string, value = 'a-long-password') {
  fireEvent.change(screen.getByLabelText(first), { target: { value } });
  fireEvent.change(screen.getByLabelText(second), { target: { value } });
}

beforeEach(() => vi.unstubAllGlobals());
afterEach(() => vi.unstubAllGlobals());

describe('InvitePage', () => {
  it('says the link has expired when the lookup is a 404', async () => {
    renderAt('/invite/tok-1', { [INVITE]: { status: 404, body: { detail: 'not_found' } } });
    expect(await screen.findByText('This link has expired.')).toBeTruthy();
  });

  it('sets a password and lands signed in', async () => {
    const fetchMock = renderAt('/invite/tok-1', {
      [INVITE]: { body: { email: invitee.email, name: invitee.name, google: true } },
    });
    expect(await screen.findByText(invitee.email)).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Continue with Google' }).getAttribute('href')).toBe('/api/auth/google/start?invite=tok-1');
    fillPasswords('Choose a password', 'Confirm password');
    mockFetch({ 'POST /api/auth/invite/tok-1': { body: { user: invitee } }, 'GET /api/me': { body: invitee } });
    fireEvent.click(screen.getByRole('button', { name: 'Set password and sign in' }));
    expect(await screen.findByText('HOME')).toBeTruthy();
    expect(callsTo(fetchMock, 'GET', '/api/auth/invite/tok-1')).toHaveLength(1);
  });

  it('shows the Google error the callback came back with, and hides Google when it is off', async () => {
    renderAt('/invite/tok-1?error=google_in_use', { [INVITE]: { body: { email: invitee.email, name: '', google: false } } });
    expect((await screen.findByRole('alert')).textContent).toMatch(/already linked to another user/);
    expect(screen.queryByRole('link', { name: 'Continue with Google' })).toBeNull();
  });
});

describe('ResetPasswordPage', () => {
  it('continues to the two-factor step when the account has it on', async () => {
    renderAt('/reset-password/r-1', {});
    fillPasswords('New password', 'Confirm password');
    const next = mockFetch({
      'POST /api/auth/reset': { body: { totp_required: true, challenge: 'ch-r' } },
      'POST /api/auth/login/totp': { status: 401, body: { detail: 'invalid_code' } },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save and sign in' }));
    fireEvent.change(await screen.findByLabelText('Authentication code'), { target: { value: '111111' } });
    fireEvent.click(screen.getByRole('button', { name: 'Verify' }));
    // A wrong code on a public page is an answer, not a redirect to /login.
    expect((await screen.findByRole('alert')).textContent).toMatch(/That code didn't work/);
    expect(JSON.parse(callsTo(next, 'POST', '/api/auth/reset')[0][1]!.body as string)).toEqual({ token: 'r-1', password: 'a-long-password' });
  });

  it('explains a used or expired link', async () => {
    renderAt('/reset-password/r-1', { 'POST /api/auth/reset': { status: 404, body: { detail: 'not_found' } } });
    fillPasswords('New password', 'Confirm password');
    fireEvent.click(screen.getByRole('button', { name: 'Save and sign in' }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/expired or was already used/);
  });
});
