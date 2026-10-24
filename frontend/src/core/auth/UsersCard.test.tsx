import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { User } from '../api/types';
import { CoreAppsProvider } from '../apps/CoreAppsContext';
import { SettingsPage } from '../settings/SettingsPage';
import { callsTo, mockFetch, type Reply } from '../../testing';
import type { AdminUser } from './api';
import { AuthProvider } from './AuthContext';
import UsersCard from './UsersCard';

const me = (role: User['role']): User => ({ id: 1, email: 'boss@example.com', name: 'Boss', role, tz: 'UTC' });
const row = (id: number, extra: Partial<AdminUser> = {}): AdminUser => ({
  id, email: `u${id}@example.com`, name: `User ${id}`, role: 'member', tz: null, is_active: true, invite_pending: false,
  has_password: true, google_linked: false, totp_enabled: false, invited_by: null, last_login_at: null,
  deactivated_at: null, created_at: '2026-10-01T00:00:00Z', ...extra,
});
const LIST = 'GET /api/auth/users?status=active';

function renderSettings(role: User['role'], entry: string, routes: Record<string, Reply> = {}) {
  const fetchMock = mockFetch({ 'GET /api/me': { body: me(role) }, 'GET /api/core/apps': { body: [] }, ...routes });
  render(
    <MemoryRouter initialEntries={[entry]}>
      <AuthProvider>
        <CoreAppsProvider>
          <Routes><Route path="/settings/*" element={<SettingsPage />} /></Routes>
        </CoreAppsProvider>
      </AuthProvider>
    </MemoryRouter>,
  );
  return fetchMock;
}

function renderCard(routes: Record<string, Reply>) {
  const fetchMock = mockFetch({ 'GET /api/me': { body: me('admin') }, ...routes });
  render(<MemoryRouter><AuthProvider><UsersCard /></AuthProvider></MemoryRouter>);
  return fetchMock;
}

beforeEach(() => window.history.pushState({}, '', '/settings'));
afterEach(() => vi.unstubAllGlobals());

describe('Settings sections by role', () => {
  it('gives a member the Account section and never the Users or Sign-in sections, even by deep link', async () => {
    const fetchMock = renderSettings('member', '/settings/users');
    const nav = await screen.findByRole('navigation', { name: 'Settings sections' });
    expect(await within(nav).findByRole('link', { name: 'Account' })).toBeTruthy();
    expect(within(nav).queryByRole('link', { name: 'Users' })).toBeNull();
    expect(within(nav).queryByRole('link', { name: 'Sign-in' })).toBeNull();
    // The deep link says so in place instead of loading the admin cards.
    expect(await screen.findByRole('heading', { name: 'Not allowed' })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Users' })).toBeNull();
    expect(callsTo(fetchMock, 'GET', '/api/auth/users?status=active')).toHaveLength(0);
  });

  it('gives an admin Account, Users and Sign-in, and the Users card lists accounts', async () => {
    renderSettings('admin', '/settings/users', { [LIST]: { body: [row(1, { email: 'boss@example.com', name: 'Boss', role: 'admin' }), row(2)] } });
    const nav = await screen.findByRole('navigation', { name: 'Settings sections' });
    for (const name of ['Account', 'Users', 'Sign-in']) expect(await within(nav).findByRole('link', { name })).toBeTruthy();
    expect(await screen.findByText('User 2')).toBeTruthy();
  });
});

describe('UsersCard', () => {
  it('invites someone and shows the link to copy, saying when it was not emailed', async () => {
    const fetchMock = renderCard({
      [LIST]: { body: [] },
      'POST /api/auth/users': { body: { user: row(5, { email: 'new@example.com', invite_pending: true }), invite_url: 'http://x.test/invite/abc', mailed: false } },
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Invite someone' }));
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: ' new@example.com ' } });
    fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'admin' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send invite' }));
    const panel = await screen.findByRole('status');
    expect(panel.textContent).toMatch(/Email isn't set up on this install, so send new@example.com this link yourself/);
    expect((within(panel).getByLabelText('Invite link') as HTMLInputElement).value).toBe('http://x.test/invite/abc');
    expect(JSON.parse(callsTo(fetchMock, 'POST', '/api/auth/users')[0][1]!.body as string)).toEqual({ email: 'new@example.com', name: '', role: 'admin' });
  });

  it('shows the server sentence for a duplicate email', async () => {
    renderCard({ [LIST]: { body: [] }, 'POST /api/auth/users': { status: 409, body: { detail: 'A user with that email already exists.' } } });
    fireEvent.click(await screen.findByRole('button', { name: 'Invite someone' }));
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'dup@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send invite' }));
    expect((await screen.findByRole('alert')).textContent).toBe('A user with that email already exists.');
  });

  it('explains the last-admin refusal when demoting an admin', async () => {
    renderCard({
      [LIST]: { body: [row(1, { email: 'boss@example.com', name: 'Boss', role: 'admin' }), row(3, { role: 'admin', name: 'Other Admin' })] },
      'PATCH /api/auth/users/3': { status: 409, body: { detail: 'last_admin' } },
    });
    const other = (await screen.findByText('Other Admin')).closest('li')!;
    fireEvent.click(within(other).getByRole('button', { name: 'Edit' }));
    fireEvent.change(within(other).getByLabelText('Role'), { target: { value: 'member' } });
    fireEvent.click(within(other).getByRole('button', { name: 'Save' }));
    expect((await within(other).findByRole('alert')).textContent).toMatch(/at least one active admin/);
  });

  it('does not offer to deactivate or demote yourself', async () => {
    renderCard({ [LIST]: { body: [row(1, { email: 'boss@example.com', name: 'Boss', role: 'admin' }), row(2)] } });
    const mine = (await screen.findByText('Boss')).closest('li')!;
    await screen.findByText('(you)');
    expect(within(mine).queryByRole('button', { name: 'Deactivate' })).toBeNull();
    fireEvent.click(within(mine).getByRole('button', { name: 'Edit' }));
    expect((within(mine).getByLabelText('Role') as HTMLSelectElement).disabled).toBe(true);
    const theirs = screen.getByText('User 2').closest('li')!;
    expect(within(theirs).getByRole('button', { name: 'Deactivate' })).toBeTruthy();
  });

  it('offers a new invite link only while the invite is pending', async () => {
    renderCard({
      [LIST]: { body: [row(1, { email: 'boss@example.com', name: 'Boss', role: 'admin' }), row(4, { invite_pending: true, has_password: false })] },
      'POST /api/auth/users/4/resend-invite': { body: { invite_url: 'http://x.test/invite/new', mailed: true } },
    });
    const pending = (await screen.findByText('User 4')).closest('li')!;
    expect(within(screen.getByText('Boss').closest('li')!).queryByRole('button', { name: 'New invite link' })).toBeNull();
    fireEvent.click(within(pending).getByRole('button', { name: 'New invite link' }));
    expect((await screen.findByRole('status')).textContent).toMatch(/Invite emailed to u4@example.com/);
  });
});
