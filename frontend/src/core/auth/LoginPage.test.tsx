import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AuthStatus, User } from '../api/types';
import { callsTo, mockFetch, type Reply } from '../../testing';
import { GOOGLE_ERRORS } from './api';
import { AuthProvider } from './AuthContext';
import { LoginPage } from './LoginPage';

const status = (s: Partial<AuthStatus>): Reply => ({ body: { setup_required: false, google: false, preview: false, ...s } });
const member: User = { id: 2, email: 'm@example.com', name: 'M', role: 'member', tz: 'UTC' };

function renderLogin(routes: Record<string, Reply>, entry = '/login') {
  const fetchMock = mockFetch({ 'GET /api/me': { status: 401 }, 'GET /api/auth/status': status({}), ...routes });
  render(
    <MemoryRouter initialEntries={[entry]}>
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

const bodyOf = (fetchMock: ReturnType<typeof mockFetch>, method: string, url: string) =>
  JSON.parse(callsTo(fetchMock, method, url)[0][1]!.body as string);

async function submitPassword() {
  fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'm@example.com' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'secret-pass' } });
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
}

// The API client reads the real address bar to tell a wrong password from an expired session.
beforeEach(() => window.history.pushState({}, '', '/login'));
afterEach(() => vi.unstubAllGlobals());

describe('LoginPage', () => {
  it('shows only the password form when Google and preview are off', async () => {
    const fetchMock = renderLogin({});
    expect(await screen.findByLabelText('Email')).toBeTruthy();
    await vi.waitFor(() => expect(callsTo(fetchMock, 'GET', '/api/auth/status')).toHaveLength(1));
    expect(screen.queryByRole('link', { name: 'Continue with Google' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Member' })).toBeNull();
  });

  it('shows the Google button when enabled, as a plain link to the start route (a GET the server redirects)', async () => {
    renderLogin({ 'GET /api/auth/status': status({ google: true }) });
    const google = await screen.findByRole('link', { name: 'Continue with Google' });
    expect(google.getAttribute('href')).toBe('/api/auth/google/start');
    expect(screen.queryByRole('button', { name: 'Member' })).toBeNull();
  });

  it.each(['google_failed', 'not_invited', 'link_required', 'google_mismatch', 'google_not_configured'])(
    'explains ?error=%s from the Google callback', async code => {
      renderLogin({}, `/login?error=${code}`);
      expect((await screen.findByRole('alert')).textContent).toBe(GOOGLE_ERRORS[code]);
    },
  );

  it('shows the role picker only in preview, and signs in as the picked role', async () => {
    const fetchMock = renderLogin({
      'GET /api/auth/status': status({ preview: true }),
      'POST /api/auth/preview': { body: { user: {} } },
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Member' }));
    // After the cookie is set the page asks /api/me who that is; answer as the member now.
    mockFetch({ 'GET /api/me': { body: member } });
    expect(await screen.findByText('HOME')).toBeTruthy();
    expect(bodyOf(fetchMock, 'POST', '/api/auth/preview')).toEqual({ role: 'member' });
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
    renderLogin({ 'POST /api/auth/login': { status: 401, body: { detail: 'invalid_credentials' } } });
    await submitPassword();
    expect((await screen.findByRole('alert')).textContent).toBe("That email and password don't match an account.");
  });
});

describe('LoginPage: the two-factor step', () => {
  it('asks for a code after the password, then signs in with it and the trust choice', async () => {
    renderLogin({ 'POST /api/auth/login': { body: { totp_required: true, challenge: 'ch-1' } } });
    await submitPassword();
    const code = await screen.findByLabelText('Authentication code');
    const next = mockFetch({ 'POST /api/auth/login/totp': { body: { user: member } }, 'GET /api/me': { body: member } });
    fireEvent.change(code, { target: { value: '123456' } });
    fireEvent.click(screen.getByLabelText('Trust this browser for 30 days'));
    fireEvent.click(screen.getByRole('button', { name: 'Verify' }));
    expect(await screen.findByText('HOME')).toBeTruthy();
    expect(bodyOf(next, 'POST', '/api/auth/login/totp')).toEqual({ challenge: 'ch-1', code: '123456', trust_device: true });
  });

  it('takes a backup code instead, sent as backup_code', async () => {
    renderLogin({ 'POST /api/auth/login': { body: { totp_required: true, challenge: 'ch-1' } } });
    await submitPassword();
    fireEvent.click(await screen.findByRole('button', { name: 'Use a backup code' }));
    const next = mockFetch({ 'POST /api/auth/login/totp': { body: { user: member } }, 'GET /api/me': { body: member } });
    fireEvent.change(screen.getByLabelText('Backup code'), { target: { value: 'ABCD-EFGH' } });
    fireEvent.click(screen.getByRole('button', { name: 'Verify' }));
    expect(await screen.findByText('HOME')).toBeTruthy();
    expect(bodyOf(next, 'POST', '/api/auth/login/totp')).toEqual({ challenge: 'ch-1', backup_code: 'ABCD-EFGH', trust_device: false });
  });

  it('stays on the step after a wrong code (a 401 here is an answer, not a lost session)', async () => {
    renderLogin({
      'POST /api/auth/login': { body: { totp_required: true, challenge: 'ch-1' } },
      'POST /api/auth/login/totp': { status: 401, body: { detail: 'invalid_code' } },
    });
    await submitPassword();
    fireEvent.change(await screen.findByLabelText('Authentication code'), { target: { value: '000000' } });
    fireEvent.click(screen.getByRole('button', { name: 'Verify' }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/That code didn't work/);
    expect(screen.getByLabelText('Authentication code')).toBeTruthy();
  });

  it('goes back to the password form when the challenge has expired', async () => {
    renderLogin({
      'POST /api/auth/login': { body: { totp_required: true, challenge: 'ch-1' } },
      'POST /api/auth/login/totp': { status: 401, body: { detail: 'challenge_expired' } },
    });
    await submitPassword();
    fireEvent.change(await screen.findByLabelText('Authentication code'), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: 'Verify' }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/sign-in expired/);
    expect(screen.getByLabelText('Password')).toBeTruthy();
  });

  it('opens straight on the step when Google hands over #totp_challenge=', async () => {
    renderLogin({}, '/login#totp_challenge=from-google');
    const code = await screen.findByLabelText('Authentication code');
    const next = mockFetch({ 'POST /api/auth/login/totp': { body: { user: member } }, 'GET /api/me': { body: member } });
    fireEvent.change(code, { target: { value: '654321' } });
    fireEvent.click(screen.getByRole('button', { name: 'Verify' }));
    expect(await screen.findByText('HOME')).toBeTruthy();
    expect(bodyOf(next, 'POST', '/api/auth/login/totp').challenge).toBe('from-google');
  });
});

describe('LoginPage: forgot password', () => {
  it.each([
    [true, /If an account uses that email, a reset link is on its way/],
    [false, /can't send email, so no reset link was sent/],
  ])('answers the same whether or not the account exists (mail: %s)', async (mail, message) => {
    const fetchMock = renderLogin({ 'POST /api/auth/forgot': { status: 202, body: { mail } } });
    fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'who@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Forgot password?' }));
    // The email typed on the sign-in form carries over.
    expect((screen.getByLabelText('Email') as HTMLInputElement).value).toBe('who@example.com');
    fireEvent.click(screen.getByRole('button', { name: 'Send reset link' }));
    expect((await screen.findByRole('status')).textContent).toMatch(message);
    expect(bodyOf(fetchMock, 'POST', '/api/auth/forgot')).toEqual({ email: 'who@example.com' });
    fireEvent.click(screen.getByRole('button', { name: 'Back to sign in' }));
    expect(screen.getByLabelText('Password')).toBeTruthy();
  });
});
