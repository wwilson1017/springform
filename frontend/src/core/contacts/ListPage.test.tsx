import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { callsTo, mockFetch } from '../../testing';
import ListPage from './ListPage';
import type { ContactPage, PersonRow } from './types';

const PEOPLE = '/api/core/contacts/people';
const person = (id: number, name: string, extra: Partial<PersonRow> = {}): PersonRow => ({
  id, name, given_name: null, family_name: null, email: null, phone: null, title: null, source: null, status: null,
  tags: [], notes: null, owner_user_id: null, archived_at: null, merged_into_id: null,
  created_at: '2026-10-20T15:00:00Z', updated_at: '2026-10-20T15:00:00Z',
  primary_organization_id: null, primary_organization_name: null, ...extra,
});
const page = (items: PersonRow[]): ContactPage<PersonRow> => ({ items, total: items.length, page: 1, page_size: 50 });

/** The current query string, on the page where a test can read it. */
function Where() {
  return <span data-testid="where">{useLocation().search}</span>;
}
const search = () => screen.getByTestId('where').textContent;

function renderAt(url: string) {
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes><Route path="/people" element={<><ListPage kind="person" /><Where /></>} /></Routes>
    </MemoryRouter>,
  );
}

// jsdom has no matchMedia; the list asks it whether to render the phone layout.
beforeEach(() => vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} })));
afterEach(() => vi.unstubAllGlobals());

describe('People list filters', () => {
  it('reads the filters from the URL into the list request', async () => {
    const fetchMock = mockFetch({
      [`GET ${PEOPLE}?archived=true&tag=vip&organization_id=4&page=2&page_size=50`]: { body: { ...page([person(1, 'Ada Example', { tags: ['vip'] })]), page: 2 } },
      'GET /api/core/contacts/organizations/4': { body: { id: 4, name: 'Demo Café Group' } },
    });
    renderAt('/people?archived=true&tag=vip&organization_id=4&page=2');
    expect(await screen.findByRole('link', { name: 'Ada Example' })).toBeTruthy();
    // The organization filter shows the organization's name, not its id.
    expect(await screen.findByDisplayValue('Demo Café Group')).toBeTruthy();
    // The archived view has no duplicates panel.
    expect(callsTo(fetchMock, 'GET', `${PEOPLE}/duplicates`)).toHaveLength(0);
  });

  it('typing searches after a pause, and any filter change returns to page 1', async () => {
    const fetchMock = mockFetch({
      [`GET ${PEOPLE}?page=3&page_size=50`]: { body: { ...page([person(1, 'Ada Example')]), total: 120, page: 3 } },
      [`GET ${PEOPLE}/duplicates`]: { body: [] },
      [`GET ${PEOPLE}?q=zo%C3%AB&page=1&page_size=50`]: { body: page([person(3, 'Zoë Démo')]) },
      [`GET ${PEOPLE}?q=zo%C3%AB&archived=true&page=1&page_size=50`]: { body: page([]) },
    });
    renderAt('/people?page=3');
    expect(await screen.findByText('101–120 of 120')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Search people'), { target: { value: 'zoë' } });
    expect(search()).toBe('?q=zo%C3%AB');
    expect(await screen.findByRole('link', { name: 'Zoë Démo' })).toBeTruthy();
    // One request for the settled text, none per keystroke in between.
    expect(callsTo(fetchMock, 'GET', `${PEOPLE}?q=zo%C3%AB&page=1&page_size=50`)).toHaveLength(1);

    fireEvent.click(screen.getByLabelText('Archived'));
    expect(search()).toBe('?q=zo%C3%AB&archived=true');
    expect(await screen.findByText('No archived people match these filters.')).toBeTruthy();
  });

  it('a tag chip filters the list by that tag', async () => {
    mockFetch({
      [`GET ${PEOPLE}?page=1&page_size=50`]: { body: page([person(1, 'Ada Example', { tags: ['supplier'] })]) },
      [`GET ${PEOPLE}/duplicates`]: { body: [] },
      [`GET ${PEOPLE}?tag=supplier&page=1&page_size=50`]: { body: page([person(1, 'Ada Example', { tags: ['supplier'] })]) },
    });
    renderAt('/people');
    fireEvent.click(await screen.findByRole('button', { name: 'supplier' }));
    expect(search()).toBe('?tag=supplier');
    expect((screen.getByLabelText('Tag') as HTMLInputElement).value).toBe('supplier');
  });
});
