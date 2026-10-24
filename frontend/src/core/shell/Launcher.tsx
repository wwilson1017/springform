import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { fetchJson } from '../api/client';
import type { Badge, CoreApp } from '../api/types';
import { useCoreApps } from '../apps/CoreAppsContext';
import { useAuth } from '../auth/AuthContext';
import BootFallback from '../components/BootFallback';
import { LoadError } from '../../shared/LoadError';
import { AppIcon } from '../../shared/icons';

const BADGE_POLL_MS = 60_000;

/**
 * Each app's badge (`{count, label?}` from its manifest `badge` route), polled every 60 s but
 * only while the tab is visible, and refreshed the moment it becomes visible again. A failing
 * badge just shows nothing.
 */
function useBadges(apps: CoreApp[] | null): Record<string, Badge> {
  const [badges, setBadges] = useState<Record<string, Badge>>({});
  useEffect(() => {
    const withBadge = (apps ?? []).filter(a => a.badge);
    if (withBadge.length === 0) return;
    let cancelled = false;
    const poll = () => {
      if (document.visibilityState !== 'visible') return;
      for (const app of withBadge) {
        fetchJson<Badge>(app.badge!).then(b => { if (!cancelled) setBadges(prev => ({ ...prev, [app.slug]: b })); }, () => {});
      }
    };
    poll();
    const timer = setInterval(poll, BADGE_POLL_MS);
    document.addEventListener('visibilitychange', poll);
    return () => {
      cancelled = true;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', poll);
    };
  }, [apps]);
  return badges;
}

/** The home screen: one tile per app the user may open. Admins also see hidden apps, marked. */
export function Launcher() {
  const { user } = useAuth();
  const { apps, error, reload } = useCoreApps();
  const badges = useBadges(apps);

  if (error) return <div className="mx-auto max-w-5xl px-4 md:px-8"><LoadError label="Couldn't load your apps" onRetry={reload} /></div>;
  if (!apps || !user) return <BootFallback variant="panel" />;

  // The server already filters by role; filtering again keeps a member from ever seeing an
  // admin-only tile if it didn't.
  const tiles = apps.filter(a => a.roles.includes(user.role) && (!a.hidden || user.role === 'admin'));

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 md:px-8">
      <h1 className="m-0 mb-6 font-display text-2xl font-medium text-sf-ink">Apps</h1>
      {tiles.length === 0 ? (
        <p className="text-sf-ink-mute">No apps are installed for your role yet.</p>
      ) : (
        <ul className="m-0 grid list-none gap-3 p-0 sm:grid-cols-2 lg:grid-cols-3">
          {tiles.map(app => <AppTile key={app.slug} app={app} badge={badges[app.slug]} />)}
        </ul>
      )}
    </div>
  );
}

function AppTile({ app, badge }: { app: CoreApp; badge?: Badge }) {
  return (
    <li>
      <Link to={app.path} aria-label={app.name}
        className={`flex h-full gap-3 rounded-lg border border-sf-line-strong bg-sf-card p-4 no-underline hover:border-sf-accent`}>
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-sf-raised text-sf-ink-mute">
          <AppIcon name={app.icon} size={22} aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="font-display text-base font-medium text-sf-ink">{app.name}</span>
            {app.hidden && <span className="rounded bg-sf-ink/6 px-1.5 py-0.5 text-xs text-sf-ink-dim">hidden</span>}
          </span>
          <span className="mt-1 line-clamp-2 block text-sm text-sf-ink-soft">{app.description}</span>
        </span>
        {badge && badge.count > 0 && (
          <span title={badge.label ?? undefined} aria-label={badge.label ?? `${badge.count} new`}
            className="h-fit min-w-6 rounded-full bg-sf-accent px-2 py-0.5 text-center text-xs font-medium text-sf-accent-ink">
            {badge.count}
          </span>
        )}
      </Link>
    </li>
  );
}
