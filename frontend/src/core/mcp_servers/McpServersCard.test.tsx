import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, mockFetch } from '../../testing';
import McpServersCard from './McpServersCard';
import { suggestPrefix, validateDraft } from './form';
import type { McpServer } from './types';

const BASE = '/api/core/mcp/servers';
const ok = { name: 'Team to-dos', url: 'https://todos.example.com/mcp', token: '', prefix: 'todos_team' };

const server = (over: Partial<McpServer> = {}): McpServer => ({
  id: 1, name: 'Team to-dos', url: 'https://todos.example.com/mcp', prefix: 'todos_team', enabled: true, has_token: true,
  tools: [{ name: 'todo_create', description: 'Create a to-do', read_only_hint: false }],
  last_discovered_at: '2026-10-24T15:00:00Z', last_error: null, created_at: '2026-10-24T15:00:00Z', updated_at: '2026-10-24T15:00:00Z',
  ...over,
});

afterEach(() => vi.unstubAllGlobals());

describe('validateDraft', () => {
  it('accepts a complete draft', () => {
    expect(validateDraft(ok)).toEqual({});
    expect(validateDraft({ ...ok, url: 'http://127.0.0.1:9100/mcp' })).toEqual({}); // the backend decides about http
  });

  it('names every field the backend would refuse', () => {
    expect(Object.keys(validateDraft({ name: ' ', url: '', token: '', prefix: '' })).sort()).toEqual(['name', 'prefix', 'url']);
    expect(validateDraft({ ...ok, url: 'ftp://example.com/mcp' }).url).toMatch(/https:\/\//);
    expect(validateDraft({ ...ok, url: 'todos.example.com' }).url).toMatch(/https:\/\//);
    expect(validateDraft({ ...ok, url: 'https://me:pw@todos.example.com/mcp' }).url).toMatch(/login/);
    for (const prefix of ['Todos', 't', '1todos', 'to-dos', 'a'.repeat(21)]) {
      expect(validateDraft({ ...ok, prefix }).prefix, prefix).toBeDefined();
    }
  });

  it('suggests a valid prefix from the name', () => {
    expect(suggestPrefix('Team To-dos')).toBe('team_to_dos');
    expect(suggestPrefix('42 Todo GTD!')).toBe('todo_gtd');
    expect(suggestPrefix('A very long server name indeed')).toHaveLength(20);
  });
});

describe('McpServersCard', () => {
  it('lists servers with their state and says every remote call asks for approval', async () => {
    mockFetch({ [`GET ${BASE}`]: { body: [server(), server({ id: 2, name: 'Broken', prefix: 'broken', tools: [], last_error: 'Timed out after 30 s' })] } });
    render(<McpServersCard />);
    expect(await screen.findByText('Team to-dos')).toBeTruthy();
    expect(screen.getByText('1 tool')).toBeTruthy();
    expect(screen.getByText('Timed out after 30 s')).toBeTruthy();
    expect(screen.getByText(/Every remote tool call asks for approval/)).toBeTruthy();
  });

  it('shows validation errors instead of posting, then posts a valid draft', async () => {
    const fetchMock = mockFetch({ [`GET ${BASE}`]: { body: [] }, [`POST ${BASE}`]: { body: server({ id: 3 }) } });
    render(<McpServersCard />);
    const add = await screen.findByRole('button', { name: 'Add server' });
    fireEvent.click(add);
    expect(await screen.findByText('Give the server a name.')).toBeTruthy();
    expect(callsTo(fetchMock, 'POST', BASE)).toHaveLength(0);

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Team to-dos' } });
    expect((screen.getByLabelText('Prefix') as HTMLInputElement).value).toBe('team_to_dos');
    fireEvent.change(screen.getByLabelText('Prefix'), { target: { value: 'todos_team' } });
    fireEvent.change(screen.getByLabelText('Address'), { target: { value: ' https://todos.example.com/mcp ' } });
    fireEvent.change(screen.getByLabelText('Token (optional)'), { target: { value: 'secret' } });
    fireEvent.click(add);
    await waitFor(() => expect(callsTo(fetchMock, 'POST', BASE)).toHaveLength(1));
    expect(JSON.parse(callsTo(fetchMock, 'POST', BASE)[0][1]!.body as string)).toEqual(
      { name: 'Team to-dos', url: 'https://todos.example.com/mcp', token: 'secret', prefix: 'todos_team' },
    );
    expect(await screen.findByText('todos_team.*')).toBeTruthy();
  });
});
