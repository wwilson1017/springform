/**
 * The header bell: the unread count (polled every 60 s while the tab is visible, and at once
 * when a read elsewhere changes it), a dropdown of the latest notifications, mark one read by
 * opening it (and follow its link), or all at once.
 *
 * Lifted in behaviour from CakeCRM's NotificationsBell, without its alerts section.
 */
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { fetchJson } from '../api/client';
import { IconBell } from '../../shared/icons';
import { toast } from '../../shared/toast';
import { NOTIFICATIONS, NOTIFICATIONS_CHANGED, inAppLink, markAllRead, markRead, relTime } from './notifications';
import type { AppNotification, UnreadCount } from './types';
import { BTN_LINK } from './ui';

const POLL_MS = 60_000;
const LATEST = 10;

export function NotificationBell() {
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<AppNotification[] | null>(null);
  const wrapper = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    let live = true;
    const poll = () => {
      if (document.visibilityState !== 'visible') return;
      fetchJson<UnreadCount>(`${NOTIFICATIONS}/unread-count`).then(r => { if (live) setCount(r.count); }, () => {});
    };
    poll();
    const timer = setInterval(poll, POLL_MS);
    document.addEventListener('visibilitychange', poll);
    window.addEventListener(NOTIFICATIONS_CHANGED, poll);
    return () => {
      live = false;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', poll);
      window.removeEventListener(NOTIFICATIONS_CHANGED, poll);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!wrapper.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  function toggle() {
    if (open) { setOpen(false); return; }
    setOpen(true);
    setItems(null);
    fetchJson<AppNotification[]>(`${NOTIFICATIONS}?limit=${LATEST}`).then(setItems, () => setItems([]));
  }

  async function follow(n: AppNotification) {
    setOpen(false);
    try {
      await markRead(n);
    } catch {
      toast.error("Couldn't mark the notification read.");
    }
    const link = inAppLink(n.link);
    if (link) navigate(link);
  }

  async function readAll() {
    try {
      await markAllRead();
      const at = new Date().toISOString();
      setItems(list => list && list.map(n => ({ ...n, read_at: n.read_at ?? at })));
      setCount(0);
    } catch {
      toast.error("Couldn't mark the notifications read.");
    }
  }

  return (
    <div ref={wrapper} className="relative" onKeyDown={e => { if (e.key === 'Escape') setOpen(false); }}>
      <button type="button" onClick={toggle} aria-expanded={open} aria-haspopup="dialog"
        aria-label={count ? `Notifications, ${count} unread` : 'Notifications'}
        className="relative flex h-8 w-8 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-sf-ink-mute hover:bg-sf-hover">
        <IconBell size={18} aria-hidden />
        {count > 0 && (
          <span aria-hidden className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-sf-accent px-1 text-[10px] font-semibold text-sf-accent-ink">
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>
      {open && (
        <div role="dialog" aria-label="Notifications"
          className="absolute right-0 z-30 mt-1 w-80 max-w-[calc(100vw-2rem)] rounded-md border border-sf-line-strong bg-sf-card shadow-lg">
          <div className="flex items-center justify-between border-b border-sf-line px-3 py-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-sf-ink-soft">Notifications</span>
            {count > 0 && <button type="button" className={BTN_LINK} onClick={() => void readAll()}>Mark all read</button>}
          </div>
          {!items ? <p className="m-0 px-3 py-3 text-sm text-sf-ink-dim">Loading…</p>
            : items.length === 0 ? <p className="m-0 px-3 py-3 text-sm text-sf-ink-mute">You're all caught up.</p>
            : (
              <ul className="m-0 max-h-96 list-none overflow-y-auto p-0">
                {items.map(n => (
                  <li key={n.id} className="border-b border-sf-line last:border-b-0">
                    <button type="button" onClick={() => void follow(n)}
                      className="flex w-full cursor-pointer gap-2 border-0 bg-transparent px-3 py-2 text-left font-sans hover:bg-sf-hover">
                      <span aria-hidden className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${n.read_at ? 'bg-transparent' : 'bg-sf-accent'}`} />
                      <span className="min-w-0 flex-1">
                        <span className={`block text-sm ${n.read_at ? 'text-sf-ink-mute' : 'font-medium text-sf-ink'}`}>{n.title}</span>
                        {n.message && <span className="line-clamp-2 block text-xs text-sf-ink-mute">{n.message}</span>}
                        <span className="block text-xs text-sf-ink-dim">{relTime(n.created_at)}{n.read_at ? '' : ' · unread'}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          <div className="border-t border-sf-line px-3 py-2">
            <Link to="/notifications" onClick={() => setOpen(false)} className="text-xs text-sf-accent-text">See all notifications</Link>
          </div>
        </div>
      )}
    </div>
  );
}
