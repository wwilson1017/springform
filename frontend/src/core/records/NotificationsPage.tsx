/** /notifications: the user's notifications, newest first, with an unread filter. */
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { useJson } from '../api/useJson';
import { formatDate } from '../../shared/formatDate';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { NOTIFICATIONS, inAppLink, markAllRead, markRead } from './notifications';
import type { AppNotification } from './types';
import { BTN_SECONDARY, H_PAGE, MUTED, PAGE } from './ui';

// simplification: the newest 200 (the server's page cap); upgrade path: page with a before-id cursor.
const LIMIT = 200;

export default function NotificationsPage() {
  const [unreadOnly, setUnreadOnly] = useState(false);
  const { data, error, reload, setData } = useJson<AppNotification[]>(`${NOTIFICATIONS}?limit=${LIMIT}${unreadOnly ? '&unread=true' : ''}`);
  const navigate = useNavigate();

  async function open(n: AppNotification) {
    try {
      await markRead(n);
      if (data) setData(data.map(x => (x.id === n.id ? { ...x, read_at: x.read_at ?? new Date().toISOString() } : x)));
    } catch {
      toast.error("Couldn't mark the notification read.");
    }
    const link = inAppLink(n.link);
    if (link) navigate(link);
  }

  async function readAll() {
    try {
      await markAllRead();
      reload();
    } catch {
      toast.error("Couldn't mark the notifications read.");
    }
  }

  return (
    <div className={`${PAGE} max-w-3xl`}>
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <h1 className={`${H_PAGE} flex-1`}>Notifications</h1>
        <div role="group" aria-label="Show" className="flex overflow-hidden rounded-md border border-sf-line-strong">
          {([false, true] as const).map(u => (
            <button key={String(u)} type="button" aria-pressed={unreadOnly === u} onClick={() => setUnreadOnly(u)}
              className={`cursor-pointer border-0 px-3 py-1.5 font-sans text-sm ${unreadOnly === u ? 'bg-sf-raised text-sf-ink' : 'bg-transparent text-sf-ink-soft hover:bg-sf-hover'}`}>
              {u ? 'Unread' : 'All'}
            </button>
          ))}
        </div>
        <button type="button" className={BTN_SECONDARY} onClick={() => void readAll()}>Mark all read</button>
      </div>
      {error ? <LoadError label="Couldn't load your notifications" onRetry={reload} />
        : !data ? <p className={MUTED}>Loading…</p>
        : data.length === 0 ? <p className={MUTED}>{unreadOnly ? 'Nothing unread.' : 'No notifications yet.'}</p>
        : (
          <ul className="m-0 list-none divide-y divide-sf-line rounded-md border border-sf-line p-0">
            {data.map(n => (
              <li key={n.id}>
                <button type="button" onClick={() => void open(n)}
                  className="flex w-full cursor-pointer gap-3 border-0 bg-transparent px-4 py-3 text-left font-sans hover:bg-sf-hover">
                  <span aria-hidden className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${n.read_at ? 'bg-transparent' : 'bg-sf-accent'}`} />
                  <span className="min-w-0 flex-1">
                    <span className={`block text-sm ${n.read_at ? 'text-sf-ink-mute' : 'font-medium text-sf-ink'}`}>{n.title}</span>
                    {n.message && <span className="block whitespace-pre-wrap text-sm text-sf-ink-mute">{n.message}</span>}
                  </span>
                  <span className="shrink-0 text-xs text-sf-ink-dim">{formatDate(n.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
    </div>
  );
}
