import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mockFetch, type Reply } from '../../testing';
import type { User } from '../api/types';
import { CoreAppsProvider } from '../apps/CoreAppsContext';
import { AuthProvider } from '../auth/AuthContext';
import { RequestsPage } from './Requests';

const user = (role: User['role']): User => ({ id: 1, email: 'a@example.com', name: 'A', role, tz: 'UTC' });

function renderRequests(role: User['role'], configured: boolean, post: Reply) {
  mockFetch({
    'GET /api/me': { body: user(role) },
    'GET /api/core/apps': { body: [] },
    'GET /api/core/requests/config': { body: { configured, warning_text: 'Leave out passwords.', repo: null } },
    'GET /api/core/requests?state=open&limit=200': { body: [] },
    'POST /api/core/requests': post,
  });
  render(<MemoryRouter><AuthProvider><CoreAppsProvider><RequestsPage /></CoreAppsProvider></AuthProvider></MemoryRouter>);
}

async function send(title: string) {
  fireEvent.click(await screen.findByRole('button', { name: 'New request' }));
  expect(await screen.findByText('Leave out passwords.')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Title'), { target: { value: title } });
  fireEvent.click(screen.getByRole('button', { name: 'Send request' }));
}

afterEach(() => vi.unstubAllGlobals());

describe('RequestsPage', () => {
  it('says "Not sent" on 409 github_not_configured and points an admin at the integration settings', async () => {
    renderRequests('admin', false, { status: 409, body: { detail: 'github_not_configured' } });
    await send('Add a delivery date');
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Not sent.');
    expect(alert.querySelector('a')?.getAttribute('href')).toBe('/settings/integrations');
  });

  it('tells a member to ask an admin, and offers no Refresh', async () => {
    renderRequests('member', false, { status: 409, body: { detail: 'github_not_configured' } });
    expect(await screen.findByText(/Ask an admin to connect it/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Refresh' })).toBeNull();
  });

  it('shows the new request with its GitHub link', async () => {
    renderRequests('member', true, { body: {
      id: 1, issue_number: 12, url: 'https://github.com/example/repo/issues/12', state: 'open', title: 'Add a delivery date',
      app: 'core', description: '', labels: ['request', 'app:core'], requested_by: { id: 1, name: 'A' },
      created_at: '2026-10-24T03:00:00Z', updated_at: '2026-10-24T03:00:00Z',
    } });
    await send('Add a delivery date');
    const status = await screen.findByRole('status');
    expect(status.textContent).toContain('#12');
    expect(screen.getByRole('link', { name: 'View it on GitHub' }).getAttribute('href')).toBe('https://github.com/example/repo/issues/12');
  });
});
