import { describe, expect, it } from 'vitest';
import { applyEvent, fromServer, renderUnits, type ChatMessage, type Part, type ToolPart } from './chatModel';
import type { ChatEvent, ServerMessage } from './types';

const row = (
  id: number,
  role: ServerMessage['role'],
  text: string,
  tool_calls: ServerMessage['tool_calls'] = [],
): ServerMessage => ({
  id,
  role,
  text,
  tool_calls,
  model: role === 'assistant' ? 'm' : null,
  created_at: '2026-10-24T10:00:00Z',
});

describe('fromServer', () => {
  it("merges one turn's assistant rows into a bubble and gives a pending run its card", () => {
    const msgs = fromServer([
      row(1, 'user', 'make a widget'),
      row(2, 'assistant', 'Proposing it.', [
        {
          tool: 'example_create_widget',
          tool_use_id: 't1',
          args: { name: 'A' },
          tool_run_id: 9,
          status: 'pending',
          can_always_allow: true,
          change_list: false,
          result: null,
          error: null,
        },
      ]),
      row(3, 'assistant', 'Waiting for you.'),
      row(4, 'tool', 'ignored'),
    ]);
    expect(msgs.map((m) => m.role)).toEqual(['user', 'assistant']);
    expect(msgs[1].parts).toEqual([
      { kind: 'text', text: 'Proposing it.' },
      {
        kind: 'tool',
        tool: 'example_create_widget',
        toolUseId: 't1',
        args: { name: 'A' },
        status: 'pending',
        result: undefined,
        error: null,
        runId: 9,
        canAlwaysAllow: true,
        changeList: false,
        confirm: { phase: 'pending' },
      },
      { kind: 'text', text: 'Waiting for you.' },
    ]);
  });

  it('shows a resolved run as a plain tool call, without a card', () => {
    const [m] = fromServer([
      row(2, 'assistant', '', [
        {
          tool: 't',
          tool_use_id: 'u',
          args: {},
          tool_run_id: 1,
          status: 'denied',
          result: null,
          error: null,
          can_always_allow: false,
          change_list: false,
        },
      ]),
    ]);
    expect(m.parts[0]).toMatchObject({ kind: 'tool', status: 'denied' });
    expect('confirm' in m.parts[0]).toBe(false);
  });
});

describe('applyEvent', () => {
  it('settles the card of a cut-off call that never ran', () => {
    const events: ChatEvent[] = [
      { type: 'tool_start', tool: 'example_list_widgets', tool_use_id: 'c1' },
      {
        type: 'tool_end',
        tool: 'example_list_widgets',
        tool_use_id: 'c1',
        tool_run_id: null,
        status: 'error',
        result: { error: 'Not run: the reply was cut off.' },
        elapsed_ms: 0,
      },
    ];
    const start: ChatMessage = { id: 'a', role: 'assistant', parts: [], streaming: true };
    expect(events.reduce(applyEvent, start).parts[0]).toMatchObject({ kind: 'tool', status: 'error', runId: null });
  });

  it('builds text and tool parts in stream order, and a confirm turns the call into a card', () => {
    const events: ChatEvent[] = [
      { type: 'text', text: 'On ' },
      { type: 'text', text: 'it.' },
      { type: 'tool_start', tool: 'example_list_widgets', tool_use_id: 'r1' },
      { type: 'tool_args', tool: 'example_list_widgets', tool_use_id: 'r1', args: {}, description: 'List widgets.' },
      {
        type: 'tool_end',
        tool: 'example_list_widgets',
        tool_use_id: 'r1',
        tool_run_id: 1,
        status: 'done',
        result: [],
        elapsed_ms: 4,
      },
      { type: 'tool_start', tool: 'example_create_widget', tool_use_id: 'w1' },
      {
        type: 'tool_args',
        tool: 'example_create_widget',
        tool_use_id: 'w1',
        args: { name: 'B' },
        description: 'Model instructions.',
      },
      {
        type: 'confirm',
        tool_run_id: 2,
        tool: 'example_create_widget',
        tool_use_id: 'w1',
        msg_id: 5,
        args: { name: 'B' },
        summary: 'Create.',
      },
      { type: 'text', text: 'Approve it?' },
      { type: 'done', model: 'fake' },
    ];
    const start: ChatMessage = { id: 'a', role: 'assistant', parts: [], streaming: true };
    const m = events.reduce(applyEvent, start);
    expect(m.streaming).toBe(false);
    expect(m.model).toBe('fake');
    expect(m.parts.map((p) => (p.kind === 'text' ? p.text : `${p.tool}:${p.status}`))).toEqual([
      'On it.',
      'example_list_widgets:done',
      'example_create_widget:pending',
      'Approve it?',
    ]);
    expect(m.parts[2]).toMatchObject({
      runId: 2,
      args: { name: 'B' },
      summary: 'Create.',
      confirm: { phase: 'pending' },
    });
  });

  it('does not use a tool description as an empty summary', () => {
    const events: ChatEvent[] = [
      { type: 'tool_start', tool: 'remote_tool', tool_use_id: 'w1' },
      {
        type: 'tool_args',
        tool: 'remote_tool',
        tool_use_id: 'w1',
        args: { value: 3 },
        description: 'Model instructions.',
      },
      {
        type: 'confirm',
        tool_run_id: 2,
        tool: 'remote_tool',
        tool_use_id: 'w1',
        msg_id: 5,
        args: { value: 3 },
        summary: '',
      },
    ];
    const start: ChatMessage = { id: 'a', role: 'assistant', parts: [] };
    expect(events.reduce(applyEvent, start).parts[0]).toMatchObject({
      summary: undefined,
      description: 'Model instructions.',
      args: { value: 3 },
      confirm: { phase: 'pending' },
    });
  });

  it('records a stream error on the message', () => {
    const m = applyEvent(
      { id: 'a', role: 'assistant', parts: [], streaming: true },
      { type: 'error', error: 'Provider error' },
    );
    expect(m).toMatchObject({ streaming: false, error: 'Provider error' });
  });
});

describe('renderUnits', () => {
  const card = (id: string, batch: string | null, args: Record<string, unknown> = {}): ToolPart => ({
    kind: 'tool',
    tool: 'save',
    toolUseId: id,
    args,
    status: 'pending',
    runId: 1,
    batch,
    confirm: { phase: 'pending' },
  });

  it('draws cards sharing a batch as one unit at the first member, and keeps a group of one plain', () => {
    const parts: Part[] = [
      { kind: 'text', text: 'Saving.' },
      card('a', 'k1'),
      card('b', 'k2'),
      card('c', 'k1'),
      { kind: 'tool', tool: 'read', toolUseId: 'r', status: 'done' },
    ];
    const units = renderUnits(parts);
    expect(units.map((u) => (u.kind === 'batch' ? `batch:${u.members.map((m) => m.toolUseId)}` : u.kind))).toEqual([
      'text',
      'batch:a,c',
      'tool',
      'tool',
    ]);
  });

  it('carries the key from a confirm event and from a reload', () => {
    const m = applyEvent(
      { id: 'm', role: 'assistant', parts: [] },
      { type: 'confirm', tool_run_id: 3, tool: 'save', tool_use_id: 'u', msg_id: 2, args: {}, summary: '', batch: 'k' },
    );
    expect(m.parts[0]).toMatchObject({ batch: 'k' });
    const [reloaded] = fromServer([
      row(2, 'assistant', '', [
        {
          tool: 'save',
          tool_use_id: 'u',
          args: {},
          tool_run_id: 3,
          status: 'pending',
          result: null,
          error: null,
          can_always_allow: false,
          change_list: false,
          batch: 'k',
        },
      ]),
    ]);
    expect(reloaded.parts[0]).toMatchObject({ batch: 'k' });
  });
});

describe('changeList', () => {
  it('comes from a confirm event, a tool_end and a reload', () => {
    const start: ChatMessage = { id: 'm', role: 'assistant', parts: [] };
    const card = applyEvent(start, {
      type: 'confirm',
      tool_run_id: 3,
      tool: 'todos_bulk_update',
      tool_use_id: 'u',
      msg_id: 2,
      args: {},
      summary: '',
      change_list: { changes: 2, records: 2 },
    });
    expect(card.parts[0]).toMatchObject({ changeList: true });
    const ran = applyEvent(applyEvent(start, { type: 'tool_start', tool: 'todos_bulk_update', tool_use_id: 'u' }), {
      type: 'tool_end',
      tool: 'todos_bulk_update',
      tool_use_id: 'u',
      tool_run_id: 3,
      status: 'done',
      result: {},
      elapsed_ms: 5,
      change_list: true,
    });
    expect(ran.parts[0]).toMatchObject({ changeList: true });
    const [reloaded] = fromServer([
      row(2, 'assistant', '', [
        {
          tool: 'todos_bulk_update',
          tool_use_id: 'u',
          args: {},
          tool_run_id: 3,
          status: 'done',
          result: null,
          error: null,
          can_always_allow: false,
          change_list: true,
        },
      ]),
    ]);
    expect(reloaded.parts[0]).toMatchObject({ changeList: true });
  });
});

describe('a card the server settles', () => {
  it('drops its Approve card on a tool_end (a batch a new message cut short)', () => {
    const card = applyEvent(
      { id: 'm', role: 'assistant', parts: [] },
      { type: 'confirm', tool_run_id: 3, tool: 'save', tool_use_id: 'u', msg_id: 2, args: {}, summary: '', batch: 'k' },
    );
    const skipped = applyEvent(card, {
      type: 'tool_end',
      tool: 'save',
      tool_use_id: 'u',
      tool_run_id: 3,
      status: 'error',
      result: { error: 'Skipped to process your new message.' },
      elapsed_ms: 0,
    });
    expect(skipped.parts[0]).toMatchObject({ status: 'error', error: 'Skipped to process your new message.' });
    expect((skipped.parts[0] as ToolPart).confirm).toBeUndefined();
    expect(renderUnits(skipped.parts).map((u) => u.kind)).toEqual(['tool']);
  });
});
