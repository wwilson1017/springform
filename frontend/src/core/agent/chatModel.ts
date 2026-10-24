/**
 * What the chat panel renders, and the two ways it is built: from a conversation read
 * (`fromServer`) and from a live stream (`applyEvent`). An assistant message is an ordered
 * list of parts, text and tool calls interleaved as the model produced them, so a reloaded
 * thread looks like the streamed one.
 */

import type { ConfirmState } from './confirmState';
import type { ChatEvent, ServerMessage, ToolStatus } from './types';

export interface ToolPart {
  kind: 'tool';
  tool: string;
  toolUseId: string;
  args?: Record<string, unknown>;
  description?: string;
  status: ToolStatus;
  result?: unknown;
  error?: string | null;
  elapsedMs?: number;
  runId?: number | null;
  /** Present when the call waits (or waited) for approval in this view. */
  confirm?: ConfirmState;
}

export type Part = { kind: 'text'; text: string } | ToolPart;

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  parts: Part[];
  model?: string | null;
  createdAt?: string;
  streaming?: boolean;
  /** The context was summarized before this reply. */
  compacted?: boolean;
  error?: string;
}

let seq = 0;
export const localId = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${++seq}`;

/** Tool args and results as readable text. */
export const pretty = (value: unknown): string => {
  if (value === undefined || value === null) return '(none)';
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
};

export const textOf = (m: ChatMessage) =>
  m.parts.map(p => (p.kind === 'text' ? p.text : '')).join('');

/**
 * Server rows to display messages. The engine saves each loop iteration of a turn as its own
 * assistant row (text and tool calls, then the wrap-up), so consecutive assistant rows merge
 * into one bubble. A call still `pending` gets a live approval card.
 */
export function fromServer(rows: ServerMessage[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  for (const row of rows) {
    if (row.role !== 'user' && row.role !== 'assistant') continue;
    const parts: Part[] = [];
    if (row.text) parts.push({ kind: 'text', text: row.text });
    for (const c of row.tool_calls ?? []) {
      const status = c.status ?? 'error';
      parts.push({
        kind: 'tool', tool: c.tool, toolUseId: c.tool_use_id, args: c.args, status,
        result: c.result ?? undefined, error: c.error, runId: c.tool_run_id,
        ...(status === 'pending' && c.tool_run_id != null ? { confirm: { phase: 'pending' as const } } : {}),
      });
    }
    const prev = out[out.length - 1];
    if (row.role === 'assistant' && prev?.role === 'assistant') {
      prev.parts = joinText(prev.parts, parts);
      prev.model = row.model ?? prev.model;
      continue;
    }
    out.push({ id: `m${row.id}`, role: row.role, parts, model: row.model, createdAt: row.created_at });
  }
  return out;
}

/** Concatenate part lists, separating two adjacent text runs with a paragraph break. */
function joinText(a: Part[], b: Part[]): Part[] {
  const last = a[a.length - 1];
  if (last?.kind === 'text' && b[0]?.kind === 'text') {
    return [...a.slice(0, -1), { kind: 'text', text: `${last.text}\n\n${b[0].text}` }, ...b.slice(1)];
  }
  return [...a, ...b];
}

function updateTool(m: ChatMessage, toolUseId: string, patch: (p: ToolPart) => ToolPart): ChatMessage {
  return { ...m, parts: m.parts.map(p => (p.kind === 'tool' && p.toolUseId === toolUseId ? patch(p) : p)) };
}

/**
 * One stream event applied to the assistant message being streamed. Events about the
 * conversation itself (id, title, usage) are the hook's business and pass through unchanged.
 */
export function applyEvent(m: ChatMessage, e: ChatEvent): ChatMessage {
  switch (e.type) {
    case 'text': {
      const last = m.parts[m.parts.length - 1];
      return last?.kind === 'text'
        ? { ...m, parts: [...m.parts.slice(0, -1), { kind: 'text', text: last.text + e.text }] }
        : { ...m, parts: [...m.parts, { kind: 'text', text: e.text }] };
    }
    case 'tool_start':
      return { ...m, parts: [...m.parts, { kind: 'tool', tool: e.tool, toolUseId: e.tool_use_id, status: 'running' }] };
    case 'tool_args':
      return updateTool(m, e.tool_use_id, p => ({ ...p, args: e.args, description: e.description || p.description }));
    case 'tool_end':
      return updateTool(m, e.tool_use_id, p => ({
        ...p, status: e.status, result: e.result, elapsedMs: e.elapsed_ms, runId: e.tool_run_id,
        error: e.status === 'error' ? errorOf(e.result) : p.error,
      }));
    case 'confirm': {
      const known = m.parts.some(p => p.kind === 'tool' && p.toolUseId === e.tool_use_id);
      const base = known ? m : applyEvent(m, { type: 'tool_start', tool: e.tool, tool_use_id: e.tool_use_id });
      return updateTool(base, e.tool_use_id, p => ({
        ...p, status: 'pending', runId: e.tool_run_id, args: e.args, description: e.description || p.description,
        confirm: { phase: 'pending' },
      }));
    }
    case 'compacted':
      return { ...m, compacted: true };
    case 'done':
      return { ...m, model: e.model, streaming: false };
    case 'error':
      return { ...m, error: e.error, streaming: false };
    default:
      return m;
  }
}

function errorOf(result: unknown): string | null {
  return result && typeof result === 'object' && 'error' in result ? String((result as { error: unknown }).error) : null;
}

/** Every approval card in a message, for the resume decision. */
export const cardsOf = (m: ChatMessage): ConfirmState[] =>
  m.parts.flatMap(p => (p.kind === 'tool' && p.confirm ? [p.confirm] : []));
