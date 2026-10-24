/**
 * The signed-in user's conversation list (lifted in shape from Chatty's useConversations).
 * The server only ever returns the caller's own threads. Search is server-side over message
 * text (`?q=`); the newest answer wins, so a slow request for an older query never lands.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { del, fetchJson, patchJson } from '../api/client';
import type { Conversation } from './types';

export function useConversations() {
  const [list, setList] = useState<Conversation[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [query, setQuery] = useState('');
  const seqRef = useRef(0);

  const fetchList = useCallback(async (q: string) => {
    const seq = ++seqRef.current;
    try {
      const url = `/api/agent/conversations?limit=100${q.trim() ? `&q=${encodeURIComponent(q.trim())}` : ''}`;
      const data = await fetchJson<Conversation[]>(url);
      if (seq === seqRef.current) { setList(data); setFailed(false); }
    } catch {
      if (seq === seqRef.current) setFailed(true);
    }
  }, []);

  // Typing settles for 250 ms before the search goes out; the first load goes at once.
  const first = useRef(true);
  useEffect(() => {
    const wait = first.current ? 0 : 250;
    first.current = false;
    const id = setTimeout(() => void fetchList(query), wait);
    return () => clearTimeout(id);
  }, [query, fetchList]);

  const reload = useCallback(() => fetchList(query), [fetchList, query]);

  const patch = useCallback(async (id: number, body: { title?: string; is_private?: boolean }) => {
    const updated = await patchJson<Conversation>(`/api/agent/conversations/${id}`, body);
    setList(prev => prev?.map(c => (c.id === id ? updated : c)) ?? prev);
    return updated;
  }, []);

  const remove = useCallback(async (id: number) => {
    await del(`/api/agent/conversations/${id}`);
    setList(prev => prev?.filter(c => c.id !== id) ?? prev);
  }, []);

  /** A title the stream announced, without a round trip. */
  const retitle = useCallback((id: number, title: string) => {
    setList(prev => prev?.map(c => (c.id === id ? { ...c, title } : c)) ?? prev);
  }, []);

  return { list, failed, query, setQuery, reload, patch, remove, retitle };
}
