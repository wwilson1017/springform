import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ConfirmHost } from '../../shared/ConfirmHost';
import { callsTo, mockFetch, type Reply } from '../../testing';
import McpLinksCard from './McpLinksCard';
import settingsCards from './settingsCards';

const LINKS = '/api/core/mcp/links';
const TOKEN = 'tok_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG';
const saved = { id: 7, label: 'Claude Desktop', created_at: '2026-11-02T09:00:00Z', last_used_at: null };

afterEach(() => vi.unstubAllGlobals());

function renderCard(routes: Record<string, Reply>) {
  const fetchMock = mockFetch(routes); // routes are read per call, so a test can change replies mid-way
  render(
    <>
      <McpLinksCard />
      <ConfirmHost />
    </>,
  );
  return fetchMock;
}

describe('McpLinksCard', () => {
  it('is a member-visible section', () => {
    expect(settingsCards.map((s) => [s.id, s.cards.map((c) => c.adminOnly)])).toEqual([['mcp', [false]]]);
  });

  it('shows a new link once, with setup instructions, and forgets it on Done', async () => {
    const routes: Record<string, Reply> = {
      [`GET ${LINKS}`]: { body: [] },
      [`POST ${LINKS}`]: { status: 201, body: { ...saved, url: `http://localhost:8000/mcp/${TOKEN}`, token: TOKEN } },
    };
    const fetchMock = renderCard(routes);
    expect(await screen.findByText('No links yet.')).toBeTruthy();

    routes[`GET ${LINKS}`] = { body: [saved] }; // the list never carries the token
    fireEvent.change(screen.getByLabelText('Link name'), { target: { value: '  Claude Desktop ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create link' }));

    const url = `http://localhost:8000/mcp/${TOKEN}`;
    expect((await screen.findByTestId('mcp-new-url')).textContent).toBe(url);
    const tabs = screen.getAllByRole('tab').map((t) => t.textContent);
    expect(tabs).toEqual(['Claude', 'ChatGPT', 'Gemini', 'Claude Code', 'Cursor', 'VS Code', 'Codex', 'Gemini CLI']);
    expect(screen.getByRole('tabpanel', { name: 'Claude' }).textContent).toContain('Add custom connector');

    fireEvent.click(screen.getByRole('tab', { name: 'ChatGPT' }));
    expect(screen.getByRole('tab', { name: 'ChatGPT' }).getAttribute('aria-selected')).toBe('true');
    expect(screen.getByRole('tabpanel').textContent).toMatch(/Add custom MCP server.*No authentication/s);
    fireEvent.click(screen.getByRole('tab', { name: 'Claude Code' }));
    expect(screen.getByText(`claude mcp add --transport http springform ${url}`)).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: 'Cursor' }));
    const install = screen.getByRole('link', { name: 'Add to Cursor' }).getAttribute('href')!;
    expect(install.startsWith('cursor://anysphere.cursor-deeplink/mcp/install?name=springform&config=')).toBe(true);
    expect(JSON.parse(atob(decodeURIComponent(install.split('config=')[1])))).toEqual({ url });
    fireEvent.click(screen.getByRole('tab', { name: 'Codex' }));
    expect(screen.getByText(`codex mcp add springform --url ${url}`)).toBeTruthy();
    expect(JSON.parse(callsTo(fetchMock, 'POST', LINKS)[0][1]!.body as string)).toEqual({ label: 'Claude Desktop' });
    expect(await screen.findByText('Never used', { exact: false })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(screen.queryByTestId('mcp-new-url')).toBeNull();
    expect(document.body.textContent).not.toContain(TOKEN);
    expect(screen.getByText('Claude Desktop')).toBeTruthy();
  });

  it('revokes a link only after the confirm', async () => {
    const routes: Record<string, Reply> = {
      [`GET ${LINKS}`]: { body: [saved] },
      [`DELETE ${LINKS}/7`]: { status: 204 },
    };
    const fetchMock = renderCard(routes);
    fireEvent.click(await screen.findByRole('button', { name: 'Revoke Claude Desktop' }));
    expect(callsTo(fetchMock, 'DELETE', `${LINKS}/7`)).toHaveLength(0);

    routes[`GET ${LINKS}`] = { body: [] };
    fireEvent.click(await screen.findByRole('button', { name: 'Revoke' }));
    expect(await screen.findByText('No links yet.')).toBeTruthy();
    expect(callsTo(fetchMock, 'DELETE', `${LINKS}/7`)).toHaveLength(1);
  });
});
