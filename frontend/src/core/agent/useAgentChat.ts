/**
 * Whisk's chat state: one conversation's messages, the turn streaming into it, and the
 * approval cards in it. Lifted in shape from Chatty's useAgentChat, cut to this backend:
 *
 * - A turn is POST /api/agent/chat read as SSE (`readEvents`). Only the new message is sent;
 *   the server assembles the history from its database.
 * - Approvals are server-side: a card posts /api/agent/confirm, and once every card of a
 *   message has resolved the turn resumes with POST /chat {conversation_id} and no message.
 * - Reconnection: the server runs a turn inside its response, so a dropped stream cannot be
 *   re-attached. When one drops (an error, or an end with no `done`/`error`), the hook re-reads
 *   the conversation with backoff and shows what the server saved, pending cards included.
 *   Stop aborts the stream and does one such read.
 * - Every async step checks that its turn is still the live one, so switching conversations
 *   mid-stream never writes into the next one.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, fetchJson, postJson } from '../api/client';
import { applyEvent, cardsOf, fromServer, localId, type ChatMessage, type ToolPart } from './chatModel';
import { confirmReducer, runStatusOf, shouldResume, type ConfirmEvent, type Decision } from './confirmState';
import { readEvents } from './sse';
import type { ConfirmResponse, ConversationDetail } from './types';

export interface ContextUsage {
  contextTokens: number;
  contextWindow: number;
}

interface Options {
  /** A turn created a conversation (or adopted one); the page puts its id in the URL. */
  onConversation?: (id: number) => void;
  onTitle?: (id: number, title: string) => void;
  /** POST /chat answered 400 no_provider: the keys went away since the page loaded. */
  onNoProvider?: () => void;
}

interface Turn {
  ctl: AbortController;
  live: boolean;
  stopped: boolean;
}

/** Backoff for re-reading the conversation after a dropped stream. */
export const RECONNECT_DELAYS_MS = [500, 1000, 2000, 4000, 8000];

export const DROP_NOTICE = 'The connection dropped. This shows what Whisk saved.';
export const LOST_NOTICE = 'The connection dropped and Whisk could not be reached. Reload the page to see what was saved.';

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

function httpError(status: number, detail: string): string {
  if (detail === 'no_provider') return 'Whisk needs an AI key before it can answer.';
  if (status === 404) return 'This conversation was not found.';
  return `Whisk could not answer (${status}${detail ? `: ${detail}` : ''}).`;
}

function confirmFailure(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) return 'Only the person who started this conversation can approve it.';
    if (e.status === 404) return 'This request no longer exists.';
    return `The server refused (${e.status}). Try again.`;
  }
  return 'Could not reach the server. Try again.';
}

export function useAgentChat(options: Options = {}) {
  const [messages, setMessagesState] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [usage, setUsage] = useState<ContextUsage | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Write-through refs: async steps read the current value, never a render's closure.
  const messagesRef = useRef<ChatMessage[]>([]);
  const convIdRef = useRef<number | null>(null);
  const turnRef = useRef<Turn | null>(null);
  const loadSeqRef = useRef(0);
  const optionsRef = useRef(options);
  useEffect(() => { optionsRef.current = options; });

  const setMessages = useCallback((next: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) => {
    messagesRef.current = typeof next === 'function' ? next(messagesRef.current) : next;
    setMessagesState(messagesRef.current);
  }, []);
  const updateMessage = useCallback((id: string, fn: (m: ChatMessage) => ChatMessage) => {
    setMessages(prev => prev.map(m => (m.id === id ? fn(m) : m)));
  }, [setMessages]);
  const adopt = useCallback((id: number | null) => {
    convIdRef.current = id;
    setConversationId(id);
  }, []);

  /** Let go of the live turn without reading anything back. */
  const detach = useCallback(() => {
    const turn = turnRef.current;
    if (!turn) return;
    turn.live = false;
    turn.ctl.abort();
    turnRef.current = null;
    setStreaming(false);
  }, []);

  /** Replace the view with the server's record. True when it did (or the turn moved on). */
  const reconcile = useCallback(async (turn: Turn, delays: number[]): Promise<boolean> => {
    const id = convIdRef.current;
    if (id == null) return false;
    for (let attempt = 0; attempt <= delays.length; attempt++) {
      if (attempt > 0) await sleep(delays[attempt - 1]);
      if (!turn.live || convIdRef.current !== id) return true;
      try {
        const conv = await fetchJson<ConversationDetail>(`/api/agent/conversations/${id}`);
        if (turn.live && convIdRef.current === id) setMessages(fromServer(conv.messages));
        return true;
      } catch (e) {
        if (e instanceof ApiError && e.status < 500) return false; // it is gone, not unreachable
      }
    }
    return false;
  }, [setMessages]);

  const runTurn = useCallback(async (body: { conversation_id: number | null; message?: string }) => {
    detach();
    const turn: Turn = { ctl: new AbortController(), live: true, stopped: false };
    turnRef.current = turn;
    const asstId = localId('a');
    setMessages(prev => [...prev, { id: asstId, role: 'assistant', parts: [], streaming: true }]);
    setStreaming(true);
    setNotice(null);

    let ended: 'terminal' | 'dropped' = 'dropped';
    try {
      const res = await fetch('/api/agent/chat', {
        method: 'POST', credentials: 'same-origin', signal: turn.ctl.signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (res.status === 401) {
        window.location.assign('/login');
        return;
      }
      if (!res.ok || !res.body) {
        const detail = await res.json().then(b => (typeof b?.detail === 'string' ? b.detail : ''), () => '');
        if (detail === 'no_provider') optionsRef.current.onNoProvider?.();
        updateMessage(asstId, m => ({ ...m, streaming: false, error: httpError(res.status, detail) }));
        ended = 'terminal';
      } else {
        await readEvents(res.body, events => {
          if (!turn.live) return;
          for (const e of events) {
            if (e.type === 'done' || e.type === 'error') ended = 'terminal';
            else if (e.type === 'conversation_id' && e.id !== convIdRef.current) {
              adopt(e.id);
              optionsRef.current.onConversation?.(e.id);
            } else if (e.type === 'title_update') optionsRef.current.onTitle?.(e.conversation_id, e.title);
            else if (e.type === 'usage') setUsage({ contextTokens: e.context_tokens, contextWindow: e.context_window });
          }
          updateMessage(asstId, m => events.reduce(applyEvent, m));
        });
      }
    } catch {
      // A dropped connection, or our own abort (Stop, or a newer turn); handled below.
    }
    if (!turn.live) return;

    if (ended === 'dropped') {
      const restored = await reconcile(turn, turn.stopped ? [] : RECONNECT_DELAYS_MS);
      if (!turn.live) return;
      if (!turn.stopped) setNotice(restored ? DROP_NOTICE : LOST_NOTICE);
    }
    // Whatever is still marked streaming stops; an empty bubble left by a stop goes away.
    setMessages(prev => prev
      .map(m => (m.id === asstId && m.streaming ? { ...m, streaming: false } : m))
      .filter(m => m.id !== asstId || m.parts.length > 0 || m.error));
    turn.live = false;
    turnRef.current = null;
    setStreaming(false);
  }, [adopt, detach, reconcile, setMessages, updateMessage]);

  const send = useCallback((text: string) => {
    const message = text.trim();
    if (!message) return;
    setMessages(prev => [...prev, { id: localId('u'), role: 'user', parts: [{ kind: 'text', text: message }] }]);
    void runTurn({ conversation_id: convIdRef.current, message });
  }, [runTurn, setMessages]);

  const stop = useCallback(() => {
    const turn = turnRef.current;
    if (!turn || turn.stopped) return;
    turn.stopped = true;
    turn.ctl.abort();
  }, []);

  /** Approve or deny one card; resume the turn when it was the message's last open card. */
  const decide = useCallback(async (msgId: string, toolUseId: string, decision: Decision) => {
    const find = () => messagesRef.current.find(m => m.id === msgId)?.parts
      .find((p): p is ToolPart => p.kind === 'tool' && p.toolUseId === toolUseId);
    const card = find();
    if (!card?.confirm || card.confirm.phase !== 'pending' || card.runId == null || turnRef.current) return;
    const conversation = convIdRef.current;

    const step = (event: ConfirmEvent, extra: Partial<ToolPart> = {}) => updateMessage(msgId, m => ({
      ...m,
      parts: m.parts.map(p => {
        if (p.kind !== 'tool' || p.toolUseId !== toolUseId || !p.confirm) return p;
        const confirm = confirmReducer(p.confirm, event);
        return { ...p, ...extra, confirm, status: runStatusOf(confirm) };
      }),
    }));

    step({ type: 'decide', decision });
    let body: ConfirmResponse;
    try {
      body = await postJson<ConfirmResponse>('/api/agent/confirm', { tool_run_id: card.runId, decision });
    } catch (e) {
      step({ type: 'failed', message: confirmFailure(e) });
      return;
    }
    step({ type: 'response', body }, {
      ...(body.result !== undefined ? { result: body.result } : {}),
      ...(body.error ? { error: body.error } : {}),
    });

    const msg = messagesRef.current.find(m => m.id === msgId);
    if (msg && conversation != null && convIdRef.current === conversation && !turnRef.current && shouldResume(cardsOf(msg))) {
      void runTurn({ conversation_id: conversation });
    }
  }, [runTurn, updateMessage]);

  /** Open a saved conversation. 'missing' covers another user's thread too (it answers 404). */
  const load = useCallback(async (id: number): Promise<'ok' | 'missing' | 'error'> => {
    detach();
    const seq = ++loadSeqRef.current;
    adopt(id);
    setMessages([]);
    setUsage(null);
    setNotice(null);
    try {
      const conv = await fetchJson<ConversationDetail>(`/api/agent/conversations/${id}`);
      if (seq === loadSeqRef.current) setMessages(fromServer(conv.messages));
      return 'ok';
    } catch (e) {
      return e instanceof ApiError && e.status === 404 ? 'missing' : 'error';
    }
  }, [adopt, detach, setMessages]);

  /** A blank chat; the next send creates the conversation. */
  const reset = useCallback(() => {
    detach();
    loadSeqRef.current++;
    adopt(null);
    setMessages([]);
    setUsage(null);
    setNotice(null);
  }, [adopt, detach, setMessages]);

  /** The conversation on screen now (for effects that must not re-run when it changes). */
  const currentId = useCallback(() => convIdRef.current, []);

  // Leaving the page lets go of the stream (the server stops the turn when the client goes).
  useEffect(() => detach, [detach]);

  return { messages, streaming, conversationId, usage, notice, send, stop, decide, load, reset, currentId };
}
