import { postJson } from '../api/client';
import type { AppNotification } from './types';

export const NOTIFICATIONS = '/api/core/notifications';

/** Fired on window after a read changes the unread count, so the bell refreshes at once. */
export const NOTIFICATIONS_CHANGED = 'sf:notifications-changed';
const changed = () => window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));

export async function markRead(n: AppNotification): Promise<void> {
  if (n.read_at) return;
  await postJson(`${NOTIFICATIONS}/${n.id}/read`);
  changed();
}

export async function markAllRead(): Promise<void> {
  await postJson(`${NOTIFICATIONS}/read-all`);
  changed();
}

/** Only a same-origin path is followed. */
export function inAppLink(link: string | null): string | null {
  return link && link.startsWith('/') && !link.startsWith('//') ? link : null;
}

/** "just now", "5m ago", "3h ago", "2d ago". */
export function relTime(iso: string, now = Date.now()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const mins = Math.round(Math.max(0, now - then) / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  return hours < 24 ? `${hours}h ago` : `${Math.round(hours / 24)}d ago`;
}
