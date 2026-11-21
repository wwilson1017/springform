import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ChatEvent, ConversationDetail } from './types';
import { ATTACH_WHILE_RUNNING, useAgentChat } from './useAgentChat';

type Handler = (init?: RequestInit) => Response | Promise<Response>;

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
      messages: [
        { id: 1, role: 'user', text: 'hi', model: null, created_at: '2026-10-24T10:00:00Z', tool_calls: [], files: [] },
      ],
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

  it("sends a deny reason and an approve's Always allow with the decision", async () => {
    const confirm = (id: number, u: string, seq: number) => ({
      type: 'confirm' as const,
      tool_run_id: id,
      tool: 'write',
      tool_use_id: u,
      msg_id: null,
      args: {},
      summary: '',
      seq,
    });
    const fn = serve({
      'POST /api/agent/chat': () =>
        sse({ type: 'conversation_id', id: 7, turn_id: 3, seq: 0 }, confirm(9, 'u1', 1), confirm(10, 'u2', 2), {
          type: 'done',
          seq: 3,
        }),
      'POST /api/agent/confirm': () => json({ status: 'done' }),
    });
    const { result } = renderHook(() => useAgentChat());
    act(() => result.current.send('hi'));
    await waitFor(() => expect(result.current.streaming).toBe(false));
    const msgId = result.current.messages.at(-1)!.id;
    await act(() => result.current.decide(msgId, 'u1', 'deny', { reason: '  Not now ', alwaysAllow: true }));
    await act(() => result.current.decide(msgId, 'u2', 'approve', { reason: 'ignored', alwaysAllow: true }));
    const bodies = fn.mock.calls
      .filter(([url]) => String(url).endsWith('/api/agent/confirm'))
      .map(([, init]) => JSON.parse((init as RequestInit).body as string));
    expect(bodies).toEqual([
      { tool_run_id: 9, decision: 'deny', reason: 'Not now' },
      { tool_run_id: 10, decision: 'approve', always_allow: true },
    ]);
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

describe('useAgentChat attachments', () => {
  const csv = () => new File(['a,b\n1,2\n'], 'parts.csv', { type: 'text/csv' });

  it('posts the message and files as multipart to /chat/upload and applies the stream', async () => {
    let sent: FormData | undefined;
    const fn = serve({
      'POST /api/agent/chat/upload': (init) => {
        sent = init?.body as FormData;
        return sse(
          { type: 'conversation_id', id: 7, turn_id: 3, seq: 0 },
          { type: 'text', text: 'Read it.', seq: 1 },
          { type: 'done', model: 'fake', seq: 2 },
        );
      },
    });
    const { result } = renderHook(() => useAgentChat({ context: { page: '/todos' } }));
    act(() => result.current.send('look', [csv()]));
    await waitFor(() => expect(result.current.streaming).toBe(false));
    expect(calls(fn)).toEqual(['POST /api/agent/chat/upload']);
    expect(JSON.parse(String(sent?.get('payload')))).toEqual({
      page: '/todos',
      conversation_id: null,
      message: 'look',
    });
    expect((sent?.getAll('files') as File[]).map((f) => f.name)).toEqual(['parts.csv']);
    expect(result.current.messages[0].files).toEqual([{ filename: 'parts.csv', kind: 'document' }]);
    expect(lastText(result.current.messages)).toBe('Read it.');
  });

  it("shows the server's sentence for a refused file", async () => {
    serve({ 'POST /api/agent/chat/upload': () => json({ detail: "'x.csv' is larger than the 25 MB limit." }, 413) });
    const { result } = renderHook(() => useAgentChat());
    act(() => result.current.send('', [csv()]));
    await waitFor(() => expect(result.current.streaming).toBe(false));
    expect(result.current.messages.at(-1)?.error).toBe("'x.csv' is larger than the 25 MB limit.");
    expect(result.current.messages[0].parts).toEqual([]);
  });

  it('Stop while photos shrink sends nothing and takes the message back', async () => {
    const fn = serve({});
    const { result } = renderHook(() => useAgentChat());
    act(() => {
      result.current.send('look', [csv()]);
      result.current.stop();
    });
    await waitFor(() => expect(result.current.streaming).toBe(false));
    expect(calls(fn)).toEqual([]);
    expect(result.current.messages).toEqual([]);
  });

  it('does not retry a files-only send that meets a running turn', async () => {
    const fn = serve({ 'POST /api/agent/chat/upload': () => json({ detail: 'turn_running' }, 409) });
    const { result } = renderHook(() => useAgentChat());
    act(() => result.current.send('', [csv()]));
    await waitFor(() => expect(result.current.streaming).toBe(false));
    expect(calls(fn)).toEqual(['POST /api/agent/chat/upload']);
    expect(result.current.messages.at(-1)?.error).toBe(ATTACH_WHILE_RUNNING); // another tab's turn: no steer
  });

  it('never queues attachments onto a running reply', async () => {
    let post!: ReturnType<typeof openStream>;
    const fn = serve({
      'POST /api/agent/chat': (init) =>
        (post = openStream(init, { type: 'conversation_id', id: 7, turn_id: 3, seq: 0 })).response,
    });
    const { result } = renderHook(() => useAgentChat());
    act(() => result.current.send('hi'));
    await waitFor(() => expect(result.current.streaming).toBe(true));
    act(() => result.current.send('and this', [csv()]));
    post.push({ type: 'done', model: 'fake', seq: 1 });
    post.close();
    await waitFor(() => expect(result.current.streaming).toBe(false));
    expect(calls(fn).filter((c) => c.includes('/chat'))).toEqual(['POST /api/agent/chat']);
    expect(result.current.messages.some((m) => m.files?.length)).toBe(false);
  });
});

describe('useAgentChat steering', () => {
  const view = (messages: ReturnType<typeof useAgentChat>['messages']) =>
    messages.map(
      (m) =>
        `${m.role}:${m.parts.map((p) => (p.kind === 'text' ? p.text : '')).join('')}${m.queued ? ' (queued)' : ''}`,
    );
  const bodies = (fn: ReturnType<typeof serve>) =>
    fn.mock.calls.filter(([u]) => u === '/api/agent/chat').map(([, init]) => JSON.parse(String(init?.body)));

  it('queues a message sent while the reply runs and opens a new bubble when the turn reads it', async () => {
    let post!: ReturnType<typeof openStream>;
    const fn = serve({
      'POST /api/agent/chat': (init) =>
        JSON.parse(String(init?.body)).message === 'also this'
          ? json({ queued: true, turn_id: 3 }, 202)
          : (post = openStream(
              init,
              { type: 'conversation_id', id: 7, turn_id: 3, seq: 0 },
              { type: 'text', text: 'Looking', seq: 1 },
            )).response,
    });
    const { result } = renderHook(() => useAgentChat());
    act(() => result.current.send('hi'));
    await waitFor(() => expect(lastText(result.current.messages)).toBe('Looking'));
    act(() => result.current.send('also this'));
    await waitFor(() => expect(bodies(fn)).toHaveLength(2));
    expect(bodies(fn)[1]).toEqual({ conversation_id: 7, message: 'also this' });
    expect(view(result.current.messages)).toEqual(['user:hi', 'assistant:Looking', 'user:also this (queued)']);
    act(() => {
      post.push({ type: 'steer', text: 'also this', seq: 2 });
      post.push({ type: 'text', text: 'Both done.', seq: 3 });
      post.push({ type: 'done', seq: 4 });
      post.close();
    });
    await waitFor(() => expect(result.current.streaming).toBe(false));
    expect(view(result.current.messages)).toEqual([
      'user:hi',
      'assistant:Looking',
      'user:also this',
      'assistant:Both done.',
    ]);
    expect(calls(fn)).toHaveLength(2); // nothing left over to continue
  });

  it('continues the conversation when the turn ended before reading a queued message', async () => {
    let post!: ReturnType<typeof openStream>;
    const fn = serve({
      'POST /api/agent/chat': (init) => {
        const body = JSON.parse(String(init?.body));
        if (body.message === 'hi')
          return (post = openStream(init, { type: 'conversation_id', id: 7, turn_id: 3, seq: 0 })).response;
        if (body.message) return json({ queued: true, turn_id: 3 }, 202);
        return sse(
          { type: 'conversation_id', id: 7, turn_id: 4, seq: 0 },
          { type: 'text', text: 'Late answer', seq: 1 },
          { type: 'done', seq: 2 },
        );
      },
    });
    const { result } = renderHook(() => useAgentChat());
    act(() => result.current.send('hi'));
    await waitFor(() => expect(result.current.conversationId).toBe(7));
    act(() => result.current.send('one more'));
    await waitFor(() => expect(bodies(fn)).toHaveLength(2));
    act(() => {
      post.push({ type: 'text', text: 'First answer', seq: 1 });
      post.push({ type: 'done', seq: 2 });
      post.close();
    });
    await waitFor(() => expect(lastText(result.current.messages)).toBe('Late answer'));
    await waitFor(() => expect(result.current.streaming).toBe(false));
    expect(bodies(fn)[2]).toEqual({ conversation_id: 7 }); // the server saved it: continue, don't resend
    expect(view(result.current.messages)).toEqual([
      'user:hi',
      'assistant:First answer',
      'user:one more',
      'assistant:Late answer',
    ]);
  });

  it('reads the next turn a queued post started when the running turn had already ended', async () => {
    let post!: ReturnType<typeof openStream>;
    serve({
      'POST /api/agent/chat': (init) =>
        JSON.parse(String(init?.body)).message === 'hi'
          ? (post = openStream(init, { type: 'conversation_id', id: 7, turn_id: 3, seq: 0 })).response
          : sse(
              { type: 'conversation_id', id: 7, turn_id: 4, seq: 0 },
              { type: 'text', text: 'Next turn', seq: 1 },
              { type: 'done', seq: 2 },
            ),
    });
    const { result } = renderHook(() => useAgentChat());
    act(() => result.current.send('hi'));
    await waitFor(() => expect(result.current.conversationId).toBe(7));
    act(() => result.current.send('again'));
    await waitFor(() => expect(view(result.current.messages)).toContain('user:again'));
    act(() => {
      post.push({ type: 'text', text: 'First', seq: 1 });
      post.push({ type: 'done', seq: 2 });
      post.close();
    });
    await waitFor(() => expect(lastText(result.current.messages)).toBe('Next turn'));
    await waitFor(() => expect(result.current.streaming).toBe(false));
    expect(view(result.current.messages)).toEqual(['user:hi', 'assistant:First', 'user:again', 'assistant:Next turn']);
  });

  it('matches a steer that arrives before its post answers, and waits for a late answer before continuing', async () => {
    let post!: ReturnType<typeof openStream>;
    const answers: ((r: Response) => void)[] = [];
    const fn = serve({
      'POST /api/agent/chat': (init) => {
        const body = JSON.parse(String(init?.body));
        if (body.message === 'hi')
          return (post = openStream(init, { type: 'conversation_id', id: 7, turn_id: 3, seq: 0 })).response;
        if (body.message) return new Promise<Response>((resolve) => answers.push(resolve));
        return sse(
          { type: 'conversation_id', id: 7, turn_id: 4, seq: 0 },
          { type: 'text', text: 'B', seq: 1 },
          { type: 'done', seq: 2 },
        );
      },
    });
    const { result } = renderHook(() => useAgentChat());
    act(() => result.current.send('hi'));
    await waitFor(() => expect(result.current.conversationId).toBe(7));
    act(() => result.current.send('a'));
    await waitFor(() => expect(answers).toHaveLength(1));
    act(() => {
      post.push({ type: 'steer', text: 'a', seq: 1 }); // read before the 202 came back
      post.push({ type: 'text', text: 'A', seq: 2 });
    });
    await waitFor(() => expect(lastText(result.current.messages)).toBe('A'));
    act(() => result.current.send('b'));
    act(() => answers[0](json({ queued: true, turn_id: 3 }, 202)));
    await waitFor(() => expect(answers).toHaveLength(2));
    act(() => {
      post.push({ type: 'done', seq: 3 });
      post.close();
    });
    await new Promise((r) => setTimeout(r, 20));
    expect(bodies(fn)).toHaveLength(3); // the end waits for b's post
    act(() => answers[1](json({ queued: true, turn_id: 3 }, 202)));
    await waitFor(() => expect(lastText(result.current.messages)).toBe('B'));
    await waitFor(() => expect(result.current.streaming).toBe(false));
    expect(bodies(fn)[3]).toEqual({ conversation_id: 7 }); // b was accepted and saved: continue, never resend
    expect(view(result.current.messages)).toEqual(['user:hi', 'user:a', 'assistant:A', 'user:b', 'assistant:B']);
  });

  it('follows a running turn it did not start when its message is queued (202), then shows what was saved', async () => {
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
      messages: [
        { id: 1, role: 'user', text: 'hi', model: null, created_at: '2026-10-24T10:00:00Z', tool_calls: [], files: [] },
        {
          id: 2,
          role: 'user',
          text: 'and this',
          model: null,
          created_at: '2026-10-24T10:00:01Z',
          tool_calls: [],
          files: [],
        },
        {
          id: 3,
          role: 'assistant',
          text: 'Both.',
          model: 'm',
          created_at: '2026-10-24T10:00:02Z',
          tool_calls: [],
          files: [],
        },
      ],
    };
    const fn = serve({
      'GET /api/agent/conversations/7': () => json(saved),
      'POST /api/agent/chat': () => json({ queued: true, turn_id: 3 }, 202),
      'GET /api/agent/turns/3/events?after=-1': () =>
        sse(
          { type: 'conversation_id', id: 7, turn_id: 3, seq: 0 },
          { type: 'text', text: 'Some', seq: 1 },
          { type: 'steer', text: 'and this', seq: 2 },
          { type: 'text', text: 'Both.', seq: 3 },
          { type: 'done', seq: 4 },
        ),
    });
    const { result } = renderHook(() => useAgentChat());
    await act(() => result.current.load(7)); // a reload while the turn runs: this view is not attached
    act(() => result.current.send('and this'));
    await waitFor(() => expect(calls(fn)).toContain('GET /api/agent/turns/3/events?after=-1'));
    await waitFor(() => expect(result.current.streaming).toBe(false));
    expect(result.current.notice).toBeNull();
    expect(view(result.current.messages)).toEqual(['user:hi', 'user:and this', 'assistant:Both.']);
    expect(calls(fn).filter((c) => c === 'POST /api/agent/chat')).toHaveLength(1); // read by the turn: no continuation
  });

  it('checks the saved conversation before continuing: an answered message is left, a lost one is sent again', async () => {
    let post!: ReturnType<typeof openStream>;
    let ys = 0;
    const row = (id: number, role: 'user' | 'assistant', text: string) => ({
      id,
      role,
      text,
      model: null,
      created_at: '2026-10-24T10:00:00Z',
      tool_calls: [],
    });
    const fn = serve({
      'POST /api/agent/chat': (init) => {
        const body = JSON.parse(String(init?.body));
        if (body.message === 'hi')
          return (post = openStream(init, { type: 'conversation_id', id: 7, turn_id: 3, seq: 0 })).response;
        if (body.message === 'x' || (body.message === 'y' && ++ys === 1))
          return json({ queued: true, turn_id: 3 }, 202);
        return sse({ type: 'conversation_id', id: 7, turn_id: 4, seq: 0 }, { type: 'done', seq: 1 });
      },
      // x was read and answered (its steer event never reached this view); y was lost in a crash.
      'GET /api/agent/conversations/7': () =>
        json({ id: 7, messages: [row(1, 'user', 'hi'), row(2, 'user', 'x'), row(3, 'assistant', 'X done.')] }),
    });
    const { result } = renderHook(() => useAgentChat());
    act(() => result.current.send('hi'));
    await waitFor(() => expect(result.current.conversationId).toBe(7));
    act(() => result.current.send('x'));
    act(() => result.current.send('y'));
    await waitFor(() => expect(bodies(fn)).toHaveLength(3));
    act(() => {
      post.push({ type: 'done', seq: 1 });
      post.close();
    });
    await waitFor(() => expect(bodies(fn)).toHaveLength(4));
    expect(bodies(fn)[3]).toEqual({ conversation_id: 7, message: 'y' });
    expect(view(result.current.messages).slice(0, 4)).toEqual(['user:hi', 'user:x', 'assistant:X done.', 'user:y']);
  });

  it('cancels the next turn a queued post started when Stop came first', async () => {
    let first!: ReturnType<typeof openStream>;
    let second!: ReturnType<typeof openStream>;
    let answer!: (r: Response) => void;
    const fn = serve({
      'POST /api/agent/chat': (init) =>
        JSON.parse(String(init?.body)).message === 'hi'
          ? (first = openStream(init, { type: 'conversation_id', id: 7, turn_id: 3, seq: 0 })).response
          : new Promise<Response>((resolve) => (answer = resolve)),
      'POST /api/agent/turns/3/cancel': () => {
        first.push({ type: 'done', stopped: true, seq: 1 });
        first.close();
        return json({ cancelled: true });
      },
      'POST /api/agent/turns/4/cancel': () => {
        second.push({ type: 'done', stopped: true, seq: 1 });
        second.close();
        return json({ cancelled: true });
      },
      'GET /api/agent/conversations/7': () => json({ id: 7, messages: [] }),
    });
    const { result } = renderHook(() => useAgentChat());
    act(() => result.current.send('hi'));
    await waitFor(() => expect(result.current.conversationId).toBe(7));
    act(() => result.current.send('x'));
    await waitFor(() => expect(answer).toBeDefined());
    act(() => result.current.stop());
    await waitFor(() => expect(calls(fn)).toContain('POST /api/agent/turns/3/cancel'));
    act(() =>
      answer((second = openStream(undefined, { type: 'conversation_id', id: 7, turn_id: 4, seq: 0 })).response),
    );
    await waitFor(() => expect(calls(fn)).toContain('POST /api/agent/turns/4/cancel'));
    await waitFor(() => expect(result.current.streaming).toBe(false));
  });
});
