import { useEffect } from 'react';
import { Link } from 'react-router';
import { useJson } from '../api/useJson';
import { BACKUPS_CHANGED, type BackupsOverview } from './types';

/** Admins only, on every page: the off-site copy is failing, unreadable or more than two days old. */
export function OffsiteWarning({ isAdmin }: { isAdmin: boolean }) {
  const { data, reload } = useJson<BackupsOverview>(isAdmin ? '/api/core/backups' : null);
  useEffect(() => {
    window.addEventListener(BACKUPS_CHANGED, reload);
    return () => window.removeEventListener(BACKUPS_CHANGED, reload);
  }, [reload]);
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
