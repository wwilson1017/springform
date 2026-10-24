import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { User } from '../api/types';
import { AuthProvider } from '../auth/AuthContext';
import type { AgentRow, AgentStatus, ChatEvent, Conversation, ConversationDetail } from './types';
import { DROP_NOTICE } from './useAgentChat';
import WhiskPage from './WhiskPage';

type Handler = (init?: RequestInit) => Response;

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const sse = (...events: ChatEvent[]) =>
  new Response(events.map(e => `data: ${JSON.stringify(e)}\n\n`).join(''), { headers: { 'Content-Type': 'text/event-stream' } });

const user = (role: User['role']): User => ({ id: 1, email: 'a@example.com', name: 'A', role, tz: 'UTC' });
const status = (configured: boolean): AgentStatus => ({
  configured, default_agent: 'whisk', providers: [], models: { default: configured ? 'm' : null, light: null },
});
const agent: AgentRow = {
  id: 1, slug: 'whisk', name: 'Whisk', personality: '', provider_override: null, model_override: null,
  model_tier: 'default', is_default: true, created_at: '2026-10-24T10:00:00Z',
};
const conversation = (id: number): Conversation => ({
  id, user_id: 1, agent_id: 1, agent_slug: 'whisk', title: 'make a widget', is_private: false,
  created_at: '2026-10-24T10:00:00Z', updated_at: '2026-10-24T10:00:00Z', compacted_at: null,
});

/** Stub fetch by "METHOD url"; a list answers its calls in order. Unlisted routes are 404. */
function serve(role: User['role'], configured: boolean, routes: Record<string, Handler | Handler[]> = {}) {
  const table: Record<string, Handler | Handler[]> = {
    'GET /api/me': () => json(user(role)),
    'GET /api/agent/status': () => json(status(configured)),
    'GET /api/agent/agents': () => json([agent]),
    'GET /api/agent/conversations?limit=100': () => json([]),
    ...routes,
  };
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const entry = table[`${init?.method ?? 'GET'} ${url}`];
    const handler = Array.isArray(entry) ? entry.shift() : entry;
    return handler ? handler(init) : json({ detail: 'not_found' }, 404);
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

const bodiesOf = (fn: ReturnType<typeof serve>, method: string, url: string) =>
  fn.mock.calls.filter(([u, init]) => u === url && init?.method === method).map(([, init]) => JSON.parse(String(init?.body)));

function renderAt(path = '/whisk') {
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes><Route path="whisk/*" element={<WhiskPage />} /></Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

async function send(text: string) {
  const box = await screen.findByRole('textbox', { name: 'Message Whisk' });
  fireEvent.change(box, { target: { value: text } });
  fireEvent.keyDown(box, { key: 'Enter' });
}

afterEach(() => vi.unstubAllGlobals());

describe('the zero-key gate', () => {
  it('shows an admin the card with a link to the AI settings, and no composer', async () => {
    serve('admin', false);
    renderAt();
    expect(await screen.findByRole('heading', { name: 'Whisk needs an AI key' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Add a key in AI settings' }).getAttribute('href')).toBe('/settings/ai');
    expect(screen.queryByRole('textbox', { name: 'Message Whisk' })).toBeNull();
  });

  it('tells a member to ask an admin, with no settings link', async () => {
    serve('member', false);
    renderAt();
    expect(await screen.findByText('Ask an admin to add one.')).toBeTruthy();
    expect(screen.queryByRole('link', { name: /AI settings/ })).toBeNull();
  });

  it('opens the chat when a key is configured', async () => {
    serve('member', true);
    renderAt();
    expect(await screen.findByRole('textbox', { name: 'Message Whisk' })).toBeTruthy();
    expect(screen.queryByText('Whisk needs an AI key')).toBeNull();
  });

  it('turns a 400 no_provider into the error and re-reads the status', async () => {
    const fn = serve('admin', true, { 'POST /api/agent/chat': () => json({ detail: 'no_provider' }, 400) });
    renderAt();
    await send('hello');
    expect(await screen.findByText('Whisk needs an AI key before it can answer.')).toBeTruthy();
    await waitFor(() => expect(fn.mock.calls.filter(([u]) => u === '/api/agent/status').length).toBe(2));
  });
});

describe('approving a write', () => {
  it('shows the card, posts the decision, shows the result and resumes the turn', async () => {
    const fn = serve('admin', true, {
      'POST /api/agent/chat': [
        () => sse(
          { type: 'conversation_id', id: 7 },
          { type: 'title_update', conversation_id: 7, title: 'make a widget' },
          { type: 'tool_start', tool: 'example_create_widget', tool_use_id: 'w1' },
          { type: 'tool_args', tool: 'example_create_widget', tool_use_id: 'w1', args: { name: 'Demo' }, description: 'Create a widget.' },
          { type: 'confirm', tool_run_id: 11, tool: 'example_create_widget', tool_use_id: 'w1', msg_id: 4, args: { name: 'Demo' }, description: 'Create a widget.' },
          { type: 'text', text: 'Waiting for your approval.' },
          { type: 'done', model: 'fake' },
        ),
        () => sse({ type: 'conversation_id', id: 7 }, { type: 'text', text: 'Created it.' }, { type: 'done', model: 'fake' }),
      ],
      'POST /api/agent/confirm': () => json({ status: 'done', result: { id: 3, name: 'Demo' } }),
    });
    renderAt();
    await send('make a widget');

    expect(await screen.findByText('Needs your approval')).toBeTruthy();
    expect(screen.getByText(/"name": "Demo"/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));

    expect(await screen.findByText('Approved and done.')).toBeTruthy();
    expect(await screen.findByText('Created it.')).toBeTruthy();
    expect(bodiesOf(fn, 'POST', '/api/agent/confirm')).toEqual([{ tool_run_id: 11, decision: 'approve' }]);
    expect(bodiesOf(fn, 'POST', '/api/agent/chat')).toEqual([
      { conversation_id: null, message: 'make a widget' },
      { conversation_id: 7 },
    ]);
    // The new conversation was already on screen: moving to its URL did not re-read it.
    expect(fn.mock.calls.some(([u]) => u === '/api/agent/conversations/7')).toBe(false);
  });

  it('a refused confirm leaves the card pending with the reason, and nothing resumes', async () => {
    const fn = serve('admin', true, {
      'POST /api/agent/chat': () => sse(
        { type: 'conversation_id', id: 7 },
        { type: 'confirm', tool_run_id: 11, tool: 'example_create_widget', tool_use_id: 'w1', msg_id: 4, args: {}, description: '' },
        { type: 'done', model: 'fake' },
      ),
      'POST /api/agent/confirm': () => json({ detail: 'not_your_conversation' }, 403),
    });
    renderAt();
    await send('make a widget');
    fireEvent.click(await screen.findByRole('button', { name: 'Deny' }));
    expect(await screen.findByText('Only the person who started this conversation can approve it.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy();
    expect(bodiesOf(fn, 'POST', '/api/agent/chat')).toHaveLength(1);
  });
});

describe('a dropped stream', () => {
  it('re-reads the conversation and shows what the server saved', async () => {
    const saved: ConversationDetail = {
      ...conversation(7),
      messages: [
        { id: 1, role: 'user', text: 'hello', model: null, created_at: '2026-10-24T10:00:00Z', tool_calls: [] },
        { id: 2, role: 'assistant', text: 'Saved answer.', model: 'fake', created_at: '2026-10-24T10:00:01Z', tool_calls: [] },
      ],
    };
    serve('admin', true, {
      // Ends after a partial answer, with no done or error.
      'POST /api/agent/chat': () => sse({ type: 'conversation_id', id: 7 }, { type: 'text', text: 'Partial' }),
      'GET /api/agent/conversations/7': () => json(saved),
    });
    renderAt();
    await send('hello');
    expect(await screen.findByText('Saved answer.')).toBeTruthy();
    expect(screen.getByText(DROP_NOTICE)).toBeTruthy();
    expect(screen.queryByText('Partial')).toBeNull();
  });
});

describe('opening a conversation by URL', () => {
  it('shows not found for an id the server will not show this user', async () => {
    serve('member', true);
    renderAt('/whisk/3');
    expect(await screen.findByText('Conversation not found')).toBeTruthy();
  });
});
