import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CoreAppsProvider } from '../apps/CoreAppsContext';
import { AuthProvider } from '../auth/AuthContext';
import { callsTo, mockFetch } from '../../testing';
import { resetUserNames } from '../../shared/users';
import DetailPage from './DetailPage';
import type { PersonDetail } from './types';

const ada: PersonDetail = {
  id: 1, name: 'Ada Example', given_name: null, family_name: null, email: 'ada@example.com', phone: null,
  title: 'Owner', source: null, status: null, tags: ['supplier'], notes: null, owner_user_id: null,
  archived_at: null, merged_into_id: null, created_at: '2026-10-20T15:00:00Z', updated_at: '2026-10-20T15:00:00Z',
  organizations: [{ organization_id: 4, name: 'Example Bakery Supply', archived_at: null, role: 'Owner', is_primary: true, started_on: null, ended_on: null }],
  channels: [{ id: 1, owner_type: 'person', owner_id: 1, kind: 'email', value: 'ada@example.com', label: 'work', is_primary: true }],
  addresses: [],
};

/** The current path, on the page where a test can read it. */
function Where() {
  return <span data-testid="where">{useLocation().pathname}</span>;
}

function renderAt(url: string, routes: Record<string, unknown>) {
  const fetchMock = mockFetch({
    'GET /api/me': { body: { id: 2, email: 'member@example.com', name: 'Member', role: 'member', tz: 'UTC' } },
    'GET /api/core/apps': { body: [] },
    'GET /api/core/timeline?entity_type=core.person&entity_id=1&limit=50': { body: [] },
    'GET /api/core/files?entity_type=core.person&entity_id=1': { body: [] },
    ...Object.fromEntries(Object.entries(routes).map(([k, body]) => [k, { body }])),
  });
  render(
    <MemoryRouter initialEntries={[url]}>
      <AuthProvider><CoreAppsProvider>
        <Routes><Route path="/people/:id" element={<><DetailPage kind="person" /><Where /></>} /></Routes>
      </CoreAppsProvider></AuthProvider>
    </MemoryRouter>,
  );
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  resetUserNames();
});

describe('Person page', () => {
  it('a merged id moves to the survivor and says so', async () => {
    const fetchMock = renderAt('/people/7', {
      'GET /api/core/contacts/people/7': { merged_into: 1 },
      'GET /api/core/contacts/people/1': ada,
    });
    expect(await screen.findByRole('heading', { level: 1, name: 'Ada Example' })).toBeTruthy();
    expect(screen.getByTestId('where').textContent).toBe('/people/1');
    expect(screen.getByRole('status').textContent).toBe('Person #7 was merged into this record.');
    expect(callsTo(fetchMock, 'GET', '/api/core/contacts/people/1')).toHaveLength(1);
  });

  it('renders the header and the sections of a live record, with no merge notice', async () => {
    renderAt('/people/1', { 'GET /api/core/contacts/people/1': ada });
    expect(await screen.findByRole('heading', { level: 1, name: 'Ada Example' })).toBeTruthy();
    expect(screen.queryByRole('status')).toBeNull();
    // The primary organization, in the header and in the Organizations section.
    expect(screen.getAllByRole('link', { name: 'Example Bakery Supply' })).toHaveLength(2);
    for (const name of ['Organizations', 'Timeline', 'Contact details', 'Addresses', 'Files']) {
      expect(screen.getByRole('heading', { level: 2, name })).toBeTruthy();
    }
    expect(screen.getByRole('button', { name: 'The primary email' })).toBeTruthy();
    // Record services title their own parts; no wrapper heading sits over them.
    expect(screen.queryByRole('heading', { name: 'Services' })).toBeNull();
    expect(await screen.findAllByRole('heading', { name: 'Reminders' })).toHaveLength(1);
  });

  it("shows a member the owner's name and lets them pick another owner by typing", async () => {
    const owned = { ...ada, owner_user_id: 5 };
    const fetchMock = renderAt('/people/1', {
      'GET /api/core/contacts/people/1': owned,
      'GET /api/core/timeline/mentionable?q=': [{ id: 5, name: 'Olive Owner' }],
      'GET /api/core/timeline/mentionable?q=pat': [{ id: 9, name: 'Pat Partner' }],
      'PATCH /api/core/contacts/people/1': { ...owned, owner_user_id: 9 },
    });
    expect(await screen.findByText('Olive Owner')).toBeTruthy();
    fireEvent.click(screen.getAllByRole('button', { name: 'Edit' })[0]); // the header's, first on the page
    const owner = screen.getByLabelText('Owner') as HTMLInputElement;
    expect(owner.value).toBe('Olive Owner');
    fireEvent.focus(owner);
    fireEvent.change(owner, { target: { value: 'pat' } });
    fireEvent.click(await screen.findByRole('option', { name: 'Pat Partner' }));
    fireEvent.click(within(screen.getByRole('form', { name: 'Edit person' })).getByRole('button', { name: 'Save' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/core/contacts/people/1')).toHaveLength(1));
    expect(JSON.parse(callsTo(fetchMock, 'PATCH', '/api/core/contacts/people/1')[0][1]!.body as string)).toEqual({ owner_user_id: 9 });
  });

  it('an unknown id says so', async () => {
    renderAt('/people/99', {});
    expect(await screen.findByText("This person doesn't exist.")).toBeTruthy();
  });
});
