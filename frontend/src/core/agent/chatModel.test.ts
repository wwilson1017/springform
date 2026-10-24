import { describe, expect, it } from 'vitest';
import { applyEvent, fromServer, type ChatMessage } from './chatModel';
import type { ChatEvent, ServerMessage } from './types';

const row = (id: number, role: string, text: string, tool_calls: ServerMessage['tool_calls'] = []): ServerMessage =>
  ({ id, role, text, tool_calls, model: role === 'assistant' ? 'm' : null, created_at: '2026-10-24T10:00:00Z' });

describe('fromServer', () => {
  it('merges one turn\'s assistant rows into a bubble and gives a pending run its card', () => {
    const msgs = fromServer([
      row(1, 'user', 'make a widget'),
      row(2, 'assistant', 'Proposing it.', [
        { tool: 'example_create_widget', tool_use_id: 't1', args: { name: 'A' }, tool_run_id: 9, status: 'pending', result: null, error: null },
      ]),
      row(3, 'assistant', 'Waiting for you.'),
      row(4, 'system', 'ignored'),
    ]);
    expect(msgs.map(m => m.role)).toEqual(['user', 'assistant']);
    expect(msgs[1].parts).toEqual([
      { kind: 'text', text: 'Proposing it.' },
      { kind: 'tool', tool: 'example_create_widget', toolUseId: 't1', args: { name: 'A' }, status: 'pending',
        result: undefined, error: null, runId: 9, confirm: { phase: 'pending' } },
      { kind: 'text', text: 'Waiting for you.' },
    ]);
  });

  it('shows a resolved run as a plain tool call, without a card', () => {
    const [m] = fromServer([row(2, 'assistant', '', [
      { tool: 't', tool_use_id: 'u', args: {}, tool_run_id: 1, status: 'denied', result: null, error: null },
    ])]);
    expect(m.parts[0]).toMatchObject({ kind: 'tool', status: 'denied' });
    expect('confirm' in m.parts[0]).toBe(false);
  });
});

describe('applyEvent', () => {
  it('builds text and tool parts in stream order, and a confirm turns the call into a card', () => {
    const events: ChatEvent[] = [
      { type: 'text', text: 'On ' },
      { type: 'text', text: 'it.' },
      { type: 'tool_start', tool: 'example_list_widgets', tool_use_id: 'r1' },
      { type: 'tool_args', tool: 'example_list_widgets', tool_use_id: 'r1', args: {}, description: 'List widgets.' },
      { type: 'tool_end', tool: 'example_list_widgets', tool_use_id: 'r1', tool_run_id: 1, status: 'done', result: [], elapsed_ms: 4 },
      { type: 'tool_start', tool: 'example_create_widget', tool_use_id: 'w1' },
      { type: 'confirm', tool_run_id: 2, tool: 'example_create_widget', tool_use_id: 'w1', msg_id: 5, args: { name: 'B' }, description: 'Create.' },
      { type: 'text', text: 'Approve it?' },
      { type: 'done', model: 'fake' },
    ];
    const start: ChatMessage = { id: 'a', role: 'assistant', parts: [], streaming: true };
    const m = events.reduce(applyEvent, start);
    expect(m.streaming).toBe(false);
    expect(m.model).toBe('fake');
    expect(m.parts.map(p => (p.kind === 'text' ? p.text : `${p.tool}:${p.status}`))).toEqual([
      'On it.', 'example_list_widgets:done', 'example_create_widget:pending', 'Approve it?',
    ]);
    expect(m.parts[2]).toMatchObject({ runId: 2, args: { name: 'B' }, description: 'Create.', confirm: { phase: 'pending' } });
  });

  it('records a stream error on the message', () => {
    const m = applyEvent({ id: 'a', role: 'assistant', parts: [], streaming: true }, { type: 'error', error: 'Provider error' });
    expect(m).toMatchObject({ streaming: false, error: 'Provider error' });
  });
});
