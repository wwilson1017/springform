import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, mockFetch } from '../../../testing';
import type { ImportPerson } from '../api';
import { ImportPage } from './ImportPage';

afterEach(() => vi.unstubAllGlobals());

const person = (name: string, organization = ''): ImportPerson =>
  ({ name, email: `${name.toLowerCase()}@example.com`, phone: '', organization, title: '', source: '', notes: '', tags: [] });
const PEOPLE = [person('Ada', 'Example Bakery Supply'), person('Zoe'), person('Linus', 'Placeholder Grocers')];

function pick() {
  render(<MemoryRouter><ImportPage /></MemoryRouter>);
  const file = new File(['name,email\nAda,ada@example.com\n'], 'people.csv', { type: 'text/csv' });
  fireEvent.change(screen.getByLabelText(/Choose a file/), { target: { files: [file] } });
  fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
}

describe('smart import', () => {
  it('previews every parsed row, imports only the ticked ones, then reports the result', async () => {
    const fetchMock = mockFetch({
      'POST /api/crm/import/parse': { body: { people: PEOPLE, method: 'csv', warnings: [] } },
      'POST /api/crm/import/confirm': { body: { created: 2, organizations_linked: 1, skipped: [], person_ids: [11, 12] } },
    });
    pick();
    const table = await screen.findByRole('table');
    expect(within(table).getAllByRole('row')).toHaveLength(4); // header + 3
    expect(within(table).getByText('Example Bakery Supply')).toBeTruthy();
    expect(callsTo(fetchMock, 'POST', '/api/crm/import/confirm')).toHaveLength(0);

    fireEvent.click(screen.getByRole('checkbox', { name: 'Import Zoe' }));
    fireEvent.click(screen.getByRole('button', { name: 'Import 2' }));
    expect(await screen.findByText('2 people imported')).toBeTruthy();
    const [, init] = callsTo(fetchMock, 'POST', '/api/crm/import/confirm')[0];
    expect(JSON.parse(init!.body as string).people.map((p: ImportPerson) => p.name)).toEqual(['Ada', 'Linus']);
    // The upload went as multipart with the file.
    const [, parseInit] = callsTo(fetchMock, 'POST', '/api/crm/import/parse')[0];
    expect((parseInit!.body as FormData).get('file')).toBeInstanceOf(File);
  });

  it('says why when a file yields nobody, and stays on the upload step', async () => {
    mockFetch({ 'POST /api/crm/import/parse': { body: { people: [], method: 'csv', warnings: ['No name column found'] } } });
    pick();
    expect((await screen.findByRole('alert')).textContent).toBe('No name column found');
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('shows the server’s reason for a refused file', async () => {
    mockFetch({ 'POST /api/crm/import/parse': { status: 422, body: { detail: 'The file is larger than 2 MB' } } });
    pick();
    expect((await screen.findByRole('alert')).textContent).toBe('The file is larger than 2 MB');
  });
});
