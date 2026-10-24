/**
 * The `@` picker's state for a textarea: typing `@` at the start or after a space lists matching
 * teammates from GET /api/core/timeline/mentionable?q=; ArrowUp/Down move, Enter or Tab picks,
 * Escape closes (until the caret leaves that `@`). Picking inserts `@[Name](user:ID)`.
 *
 * Lifted in behaviour from CakeCRM's useMentionPicker; the server reads ids from the markup, so
 * there is no picked-ids bookkeeping.
 */
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type RefObject } from 'react';
import { fetchJson } from '../api/client';
import type { UserRef } from '../api/types';
import { activeMentionQuery, applyMention, mentionMarkup } from './mentions';

export interface MentionPickerState {
  /** Matching teammates; empty when the menu is closed. */
  users: UserRef[];
  /** The highlighted row. */
  index: number;
  choose: (user: UserRef) => void;
  hover: (index: number) => void;
  /** Call first in the textarea's onKeyDown; true means the menu took the key. */
  onKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => boolean;
  /** Call from the textarea's onChange and onSelect so the query follows the caret. */
  track: (el: HTMLTextAreaElement) => void;
}

export function useMentionPicker(text: string, setText: (next: string) => void, ref: RefObject<HTMLTextAreaElement | null>): MentionPickerState {
  const [caret, setCaret] = useState<number | null>(null);
  const [dismissedAt, setDismissedAt] = useState<number | null>(null);
  const [found, setFound] = useState<{ query: string; users: UserRef[] } | null>(null);
  const [highlight, setHighlight] = useState(0);
  const pendingCaret = useRef<number | null>(null);

  const active = caret === null ? null : activeMentionQuery(text, caret);
  const open = active && active.start !== dismissedAt ? active : null;
  const query = open ? open.query : null;
  const users = query !== null && found?.query === query ? found.users : [];
  const index = Math.min(highlight, Math.max(users.length - 1, 0));

  useEffect(() => {
    if (query === null) return;
    const ctrl = new AbortController();
    fetchJson<UserRef[]>(`/api/core/timeline/mentionable?${new URLSearchParams({ q: query })}`, ctrl.signal)
      .then(list => setFound({ query, users: list }), () => {});
    return () => ctrl.abort();
  }, [query]);

  // Put the caret after an inserted mention once React has written the new value.
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && pendingCaret.current !== null) {
      el.focus();
      el.setSelectionRange(pendingCaret.current, pendingCaret.current);
      pendingCaret.current = null;
    }
  }, [text, ref]);

  const track = (el: HTMLTextAreaElement) => {
    const at = el.selectionStart === el.selectionEnd ? el.selectionStart : null;
    setCaret(at);
    setHighlight(0);
    const q = at === null ? null : activeMentionQuery(el.value, at);
    if (!q || q.start !== dismissedAt) setDismissedAt(null);
  };

  const choose = (user: UserRef) => {
    if (!open || caret === null) return;
    const next = applyMention(text, open.start, caret, mentionMarkup(user));
    pendingCaret.current = next.caret;
    setCaret(next.caret);
    setText(next.text);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>): boolean => {
    if (!open || users.length === 0 || e.nativeEvent.isComposing) return false;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlight((index + (e.key === 'ArrowDown' ? 1 : -1) + users.length) % users.length);
      return true;
    }
    if ((e.key === 'Enter' || e.key === 'Tab') && !e.shiftKey && !e.metaKey && !e.ctrlKey && !e.altKey) {
      e.preventDefault();
      choose(users[index]);
      return true;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      setDismissedAt(open.start);
      return true;
    }
    return false;
  };

  return { users, index, choose, hover: setHighlight, onKeyDown, track };
}
