import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ChatEvent, ConversationDetail } from './types';
import { useAgentChat } from './useAgentChat';

type Handler = (init?: RequestInit) => Response;

const frame = (e: ChatEvent) => new TextEncoder().encode(`data: ${JSON.stringify(e)}\n\n`);
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const sse = (...events: ChatEvent[]) =>
  new Response(events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join(''), {
    headers: { 'Content-Type': 'text/event-stream' },
  });

/** A stream that stays open after `events`: `push` adds more, `close` ends it, an abort errors it. */
function openStream(init: RequestInit | undefined, ...events: ChatEvent[]) {
  let ctl!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      ctl = c;
      events.forEach((e) => c.enqueue(frame(e)));
      init?.signal?.addEventListener('abort', () => c.error(new DOMException('aborted', 'AbortError')));
    },
  });
  return {
    response: new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }),
    push: (e: ChatEvent) => ctl.enqueue(frame(e)),
    close: () => ctl.close(),
  };
}

/** Stub fetch by "METHOD url"; unlisted routes are 404. */
function serve(routes: Record<string, Handler>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const handler = routes[`${init?.method ?? 'GET'} ${url}`];
    return handler ? handler(init) : json({ detail: 'not_found' }, 404);
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

const calls = (fn: ReturnType<typeof serve>) => fn.mock.calls.map(([u, init]) => `${init?.method ?? 'GET'} ${u}`);
const lastText = (messages: ReturnType<typeof useAgentChat>['messages']) =>
  messages
    .at(-1)
    ?.parts.map((p) => (p.kind === 'text' ? p.text : ''))
    .join('');

afterEach(() => vi.unstubAllGlobals());

describe('useAgentChat resume', () => {
  it('re-attaches after a drop and applies each event once', async () => {
    const fn = serve({
      // Ends mid-answer with no done or error: a drop.
      'POST /api/agent/chat': () =>
        sse({ type: 'conversation_id', id: 7, turn_id: 3, seq: 0 }, { type: 'text', text: 'Hel', seq: 1 }),
      'GET /api/agent/turns/3/events?after=1': () =>
        sse(
          { type: 'text', text: 'Hel', seq: 1 }, // overlaps what was already shown
          { type: 'text', text: 'lo', seq: 2 },
          { type: 'done', model: 'fake', seq: 3 },
        ),
    });
    const { result } = renderHook(() => useAgentChat());
    act(() => result.current.send('hi'));
    await waitFor(() => expect(result.current.streaming).toBe(false));
    expect(lastText(result.current.messages)).toBe('Hello');
    expect(result.current.notice).toBeNull();
    expect(calls(fn)).toEqual(['POST /api/agent/chat', 'GET /api/agent/turns/3/events?after=1']);
  });

  it('re-attaches from the last seq when the tab becomes visible', async () => {
    let attach!: ReturnType<typeof openStream>;
    const fn = serve({
      'POST /api/agent/chat': (init) =>
        openStream(init, { type: 'conversation_id', id: 7, turn_id: 3, seq: 0 }, { type: 'text', text: 'Hi', seq: 1 })
          .response,
      'GET /api/agent/turns/3/events?after=1': (init) => (attach = openStream(init)).response,
    });
    const { result } = renderHook(() => useAgentChat());
    act(() => result.current.send('hi'));
    await waitFor(() => expect(lastText(result.current.messages)).toBe('Hi'));
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await waitFor(() => expect(attach).toBeDefined());
    act(() => {
      attach.push({ type: 'text', text: ' there', seq: 2 });
      attach.push({ type: 'done', model: 'fake', seq: 3 });
      attach.close();
    });
    await waitFor(() => expect(result.current.streaming).toBe(false));
    expect(lastText(result.current.messages)).toBe('Hi there');
    expect(calls(fn)).toEqual(['POST /api/agent/chat', 'GET /api/agent/turns/3/events?after=1']);
  });

  it('Stop cancels the turn on the server, then shows what was saved', async () => {
    let post!: ReturnType<typeof openStream>;
    const saved: ConversationDetail = {
      id: 7,
      user_id: 1,
      agent_id: 1,
      agent_slug: 'whisk',
      title: 'hi',
      is_private: false,
      created_at: '2026-10-24T10:00:00Z',
      updated_at: '2026-10-24T10:00:00Z',
      compacted_at: null,
      messages: [{ id: 1, role: 'user', text: 'hi', model: null, created_at: '2026-10-24T10:00:00Z', tool_calls: [] }],
    };
    const fn = serve({
      'POST /api/agent/chat': (init) =>
        (post = openStream(
          init,
          { type: 'conversation_id', id: 7, turn_id: 3, seq: 0 },
          { type: 'text', text: 'Part', seq: 1 },
        )).response,
      'POST /api/agent/turns/3/cancel': () => {
        post.push({ type: 'done', stopped: true, seq: 2 });
        post.close();
        return json({ cancelled: true });
      },
      'GET /api/agent/conversations/7': () => json(saved),
    });
    const { result } = renderHook(() => useAgentChat());
    act(() => result.current.send('hi'));
    await waitFor(() => expect(lastText(result.current.messages)).toBe('Part'));
    act(() => result.current.stop());
    await waitFor(() => expect(result.current.streaming).toBe(false));
    expect(calls(fn)).toEqual([
      'POST /api/agent/chat',
      'POST /api/agent/turns/3/cancel',
      'GET /api/agent/conversations/7',
    ]);
    expect(result.current.messages.map((m) => m.role)).toEqual(['user']);
    expect(result.current.notice).toBeNull();
  });

  it('retries an approval continuation while the previous turn is still running', async () => {
    let posts = 0;
    const fn = serve({
      'POST /api/agent/chat': () =>
        ++posts === 1
          ? sse(
              { type: 'conversation_id', id: 7, turn_id: 3, seq: 0 },
              {
                type: 'confirm',
                tool_run_id: 9,
                tool: 'write',
                tool_use_id: 'u1',
                msg_id: null,
                args: {},
                summary: 'Write it',
                seq: 1,
              },
              { type: 'done', seq: 2 },
            )
          : posts === 2
            ? json({ detail: 'turn_running' }, 409)
            : sse(
                { type: 'conversation_id', id: 7, turn_id: 4, seq: 0 },
                { type: 'text', text: 'Done.', seq: 1 },
                {
                  type: 'done',
                  seq: 2,
                },
              ),
      'POST /api/agent/confirm': () => json({ status: 'done' }),
    });
    const { result } = renderHook(() => useAgentChat());
    act(() => result.current.send('hi'));
    await waitFor(() => expect(result.current.streaming).toBe(false));
    const msgId = result.current.messages.at(-1)!.id;
    await act(() => result.current.decide(msgId, 'u1', 'approve'));
    await waitFor(() => expect(lastText(result.current.messages)).toBe('Done.'), { timeout: 2000 });
    await waitFor(() => expect(result.current.streaming).toBe(false));
    expect(result.current.messages.some((m) => m.error)).toBe(false);
    expect(calls(fn)).toEqual([
      'POST /api/agent/chat',
      'POST /api/agent/confirm',
      'POST /api/agent/chat',
      'POST /api/agent/chat',
    ]);
  });
});
