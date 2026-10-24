/**
 * @-mentions in note bodies. A mention is stored as `@[Name](user:ID)` (the backend's
 * `timeline/service.py` MENTION pattern); the server notifies the users it names.
 *
 * `activeMentionQuery` is lifted from CakeCRM's chatterMentions.ts: an `@` opens a query only at
 * the start or after whitespace, so an email address in a note never opens the picker.
 */
import type { UserRef } from '../api/types';

/** Mirrors backend/core/timeline/service.py MENTION. */
const MENTION = /@\[([^\]\n]{1,100})\]\(user:(\d{1,12})\)/g;

export function activeMentionQuery(text: string, caret: number): { start: number; query: string } | null {
  if (caret < 0 || caret > text.length) return null;
  for (let i = caret - 1; i >= 0; i--) {
    const ch = text[i];
    if (ch === '@') {
      if (i > 0 && !/\s/.test(text[i - 1])) return null;
      const query = text.slice(i + 1, caret);
      // Right after an inserted mention's markup is not a new query.
      return query.startsWith('[') ? null : { start: i, query };
    }
    if (/\s/.test(ch)) return null;
  }
  return null;
}

/** `@[Name](user:ID)`, with characters the pattern can't carry dropped from the name. */
export function mentionMarkup(user: UserRef): string {
  const name = user.name.replace(/[[\]\n]/g, '').trim().slice(0, 100) || `User ${user.id}`;
  return `@[${name}](user:${user.id})`;
}

/** Replace the `@query` between `start` and `caret` with the markup and a space. */
export function applyMention(text: string, start: number, caret: number, markup: string): { text: string; caret: number } {
  const inserted = `${markup} `;
  return { text: text.slice(0, start) + inserted + text.slice(caret), caret: start + inserted.length };
}

export type BodySegment = string | { id: number; name: string };

/** A note body split into plain text and mentions, for rendering mentions as chips. */
export function bodySegments(body: string): BodySegment[] {
  const out: BodySegment[] = [];
  let last = 0;
  for (const m of body.matchAll(MENTION)) {
    if (m.index > last) out.push(body.slice(last, m.index));
    out.push({ id: Number(m[2]), name: m[1] });
    last = m.index + m[0].length;
  }
  if (last < body.length) out.push(body.slice(last));
  return out;
}
