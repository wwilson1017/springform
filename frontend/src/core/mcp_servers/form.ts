import type { ServerDraft } from './types';

export const PREFIX_RE = /^[a-z][a-z0-9_]{1,19}$/;

/** A prefix suggestion from the server's name: "Todo GTD" -> "todo_gtd". */
export function suggestPrefix(name: string): string {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^[^a-z]+/, '').replace(/_+$/, '');
  return slug.slice(0, 20).replace(/_+$/, '');
}

/** Field -> message for what the backend would refuse; empty when the draft can be sent. */
export function validateDraft(d: ServerDraft): Partial<Record<keyof ServerDraft, string>> {
  const errors: Partial<Record<keyof ServerDraft, string>> = {};
  if (!d.name.trim()) errors.name = 'Give the server a name.';
  let url: URL | null = null;
  try { url = new URL(d.url.trim()); } catch { /* reported below */ }
  if (!url || !['https:', 'http:'].includes(url.protocol) || !url.hostname) {
    errors.url = 'Enter the server address, starting with https://.';
  } else if (url.username || url.password) {
    errors.url = 'Leave the login out of the address; put a token in the Token field.';
  }
  if (!PREFIX_RE.test(d.prefix)) errors.prefix = '2 to 20 lowercase letters, digits or _, starting with a letter.';
  return errors;
}
