import { useEffect } from 'react';
import { Link } from 'react-router';
import { useJson } from '../api/useJson';
import { BACKUPS_CHANGED, type BackupsOverview } from './types';

const POLL_MS = 5 * 60_000;

/** Admins only, on every page: the off-site copy is failing, unreadable or more than two days old.
 * Re-read every five minutes while the tab is visible (the nightly job runs unseen), on return to
 * the tab, and at once when the Backups page changes something. */
export function OffsiteWarning({ isAdmin }: { isAdmin: boolean }) {
  const { data, reload } = useJson<BackupsOverview>(isAdmin ? '/api/core/backups' : null);
  useEffect(() => {
    if (!isAdmin) return;
    const poll = () => {
      if (document.visibilityState === 'visible') reload();
    };
    const timer = setInterval(poll, POLL_MS);
    document.addEventListener('visibilitychange', poll);
    window.addEventListener(BACKUPS_CHANGED, reload);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', poll);
      window.removeEventListener(BACKUPS_CHANGED, reload);
    };
  }, [isAdmin, reload]);
  const offsite = data?.offsite;
  if (!offsite?.configured || !(offsite.stale || offsite.last_error)) return null;
  return (
    <p
      role="alert"
      className="m-0 border-b border-sf-amber/30 bg-sf-amber/10 px-4 py-2 text-sm text-sf-amber-text md:px-7"
    >
      {offsite.last_error ? 'The last off-site backup failed.' : 'No good off-site backup in more than two days.'}{' '}
      <Link to="/backups" className="font-medium text-sf-amber-text underline">
        Open Backups
      </Link>
    </p>
  );
}
