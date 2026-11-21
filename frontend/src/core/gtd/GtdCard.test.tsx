import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ConfirmHost } from '../../shared/ConfirmHost';
import { callsTo, mockFetch, type Reply } from '../../testing';
import GtdCard from './GtdCard';
import settingsCards from './settingsCards';
import type { GtdState } from './types';

const BASE = '/api/core/gtd';
const idle: GtdState = { base_url: 'https://todogtd.com', server: null, pending: null };
const waiting: GtdState = {
  ...idle,
  pending: { user_code: 'WXYZ-2345', url: 'https://suite.example.test/connect', interval: 1, expires_in: 900 },
};
const connected: GtdState = {
  ...idle,
  server: {
    id: 3,
    name: 'GTD suite',
    url: 'https://todogtd.com/link/x',
    prefix: 'gtd',
    enabled: true,
    trusted: true,
    has_token: false,
    tools: [{ name: 'todo_list', description: 'List', read_only_hint: true }],
    last_discovered_at: '2026-11-21T09:00:00Z',
    last_error: null,
    created_at: '2026-11-21T09:00:00Z',
    updated_at: '2026-11-21T09:00:00Z',
  },
};

afterEach(() => vi.unstubAllGlobals());

function renderCard(routes: Record<string, Reply>) {
  const fetchMock = mockFetch(routes); // routes are read per call, so a test can change replies mid-way
  render(
    <>
      <GtdCard />
      <ConfirmHost />
    </>,
  );
  return fetchMock;
}

describe('GtdCard', () => {
  it('is an admin-only section', () => {
    expect(settingsCards.map((s) => [s.id, s.cards.map((c) => c.adminOnly)])).toEqual([['gtd-suite', [true]]]);
  });

  it('connects: shows the code and a new-tab link, polls, then shows it connected', async () => {
    const routes: Record<string, Reply> = {
      [`GET ${BASE}`]: { body: idle },
      [`POST ${BASE}/connect`]: { body: waiting },
      [`POST ${BASE}/connect/poll`]: { body: waiting },
    };
    const fetchMock = renderCard(routes);
    fireEvent.click(await screen.findByRole('button', { name: 'Connect' }));
    expect((await screen.findByLabelText('Connect code')).textContent).toBe('WXYZ-2345');
    const open = screen.getByRole('link', { name: /Open the GTD suite/ });
    expect(open.getAttribute('href')).toBe('https://suite.example.test/connect');
    expect(open.getAttribute('target')).toBe('_blank');
    expect(open.getAttribute('rel')).toBe('noopener noreferrer');

    await waitFor(() => expect(callsTo(fetchMock, 'POST', `${BASE}/connect/poll`).length).toBe(1), { timeout: 2500 });
    routes[`POST ${BASE}/connect/poll`] = { body: connected };
    expect(await screen.findByRole('button', { name: 'Disconnect' }, { timeout: 2500 })).toBeTruthy();
    expect(screen.getByText(/1 tools/)).toBeTruthy();
  });

  it('disconnects after the confirm', async () => {
    const fetchMock = renderCard({ [`GET ${BASE}`]: { body: connected }, [`DELETE ${BASE}`]: { body: idle } });
    fireEvent.click(await screen.findByRole('button', { name: 'Disconnect' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Disconnect' }));
    expect(await screen.findByRole('button', { name: 'Connect' })).toBeTruthy();
    expect(callsTo(fetchMock, 'DELETE', BASE)).toHaveLength(1);
  });

  it('drops a poll answer that arrives after Cancel', async () => {
    let answer: (r: Response) => void = () => {};
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const key = `${init?.method ?? 'GET'} ${String(input)}`;
      if (key === `POST ${BASE}/connect/poll`) return new Promise<Response>((resolve) => (answer = resolve));
      const body = key === `GET ${BASE}` ? waiting : key === `DELETE ${BASE}` ? idle : { detail: 'not_found' };
      return new Response(JSON.stringify(body), { status: body === idle || body === waiting ? 200 : 404 });
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<GtdCard />);
    await screen.findByLabelText('Connect code');
    await waitFor(() => expect(fetchMock.mock.calls.some(([, i]) => i?.method === 'POST')).toBe(true), {
      timeout: 2500,
    });
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(await screen.findByRole('button', { name: 'Connect' })).toBeTruthy();
    answer(new Response(JSON.stringify(connected), { status: 200 }));
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole('button', { name: 'Disconnect' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Connect' })).toBeTruthy();
  });

  it('says why an expired code failed', async () => {
    renderCard({
      [`GET ${BASE}`]: { body: waiting },
      [`POST ${BASE}/connect/poll`]: { status: 409, body: { detail: 'gtd_connect_expired' } },
    });
    expect(await screen.findByText(/That code expired/, undefined, { timeout: 2500 })).toBeTruthy();
  });

  it('keeps polling after a failed poll', async () => {
    const routes: Record<string, Reply> = {
      [`GET ${BASE}`]: { body: waiting },
      [`POST ${BASE}/connect/poll`]: { status: 502, body: { detail: "Couldn't reach the GTD suite: Timed out" } },
    };
    const fetchMock = renderCard(routes);
    expect(await screen.findByText(/Couldn't reach the GTD suite/, undefined, { timeout: 2500 })).toBeTruthy();
    routes[`POST ${BASE}/connect/poll`] = { body: connected };
    expect(await screen.findByRole('button', { name: 'Disconnect' }, { timeout: 2500 })).toBeTruthy();
    expect(callsTo(fetchMock, 'POST', `${BASE}/connect/poll`).length).toBe(2);
    expect(screen.queryByText(/Couldn't reach the GTD suite/)).toBeNull();
  });
});
