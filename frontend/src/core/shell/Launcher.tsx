import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { fetchJson } from '../api/client';
import type { Badge, CoreApp, LauncherLink } from '../api/types';
import { useJson } from '../api/useJson';
import { useCoreApps } from '../apps/CoreAppsContext';
import { useAuth } from '../auth/AuthContext';
import BootFallback from '../components/BootFallback';
import { LoadError } from '../../shared/LoadError';
import { AppIcon } from '../../shared/icons';

const BADGE_POLL_MS = 60_000;
/**
 * Stars show once the user has this many tiles in all (apps inside folders and link tiles count), in
 * every view; a short launcher needs no sorting. Counting all apps keeps filing into folders from
 * switching stars off.
 */
const STARS_FROM_TILES = 10;

/**
 * The apps this user starred, which float to the top of the launcher.
 * simplification: kept per browser and per user in localStorage, so stars don't follow a user to
 * another device; move to a core per-user table if that matters.
 */
function useStarred(userId: number | undefined): [Set<string>, (slug: string) => void] {
  const key = `springform.launcher.starred.${userId}`;
  const read = () => {
    try {
      return new Set<string>(JSON.parse(localStorage.getItem(key) ?? '[]'));
    } catch {
      return new Set<string>();
    }
  };
  const [state, setState] = useState(() => ({ key, starred: read() }));
  // Re-read during render when the signed-in user changes (React's "adjust state on prop change").
  if (state.key !== key) setState({ key, starred: read() });
  const starred = state.starred;
  const toggle = (slug: string) => {
    const next = new Set(starred);
    if (!next.delete(slug)) next.add(slug);
    setState({ key, starred: next });
    try {
      localStorage.setItem(key, JSON.stringify([...next]));
    } catch {
      /* private mode: the stars last this visit */
    }
  };
  return [starred, toggle];
}

/**
 * Each app's badge (`{count, label?}` from its manifest `badge` route), polled every 60 s but
 * only while the tab is visible, and refreshed the moment it becomes visible again. A failing
 * badge just shows nothing.
 */
function useBadges(apps: CoreApp[] | null): Record<string, Badge> {
  const [badges, setBadges] = useState<Record<string, Badge>>({});
  useEffect(() => {
    const withBadge = (apps ?? []).filter((a) => a.badge);
    if (withBadge.length === 0) return;
    let cancelled = false;
    const poll = () => {
      if (document.visibilityState !== 'visible') return;
      for (const app of withBadge) {
        fetchJson<Badge>(app.badge!).then(
          (b) => {
            if (!cancelled) setBadges((prev) => ({ ...prev, [app.slug]: b }));
          },
          () => {},
        );
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

/**
 * The home screen: one tile per app the user may open, apps an admin filed into a folder behind one
 * folder tile. Admins also see hidden apps, marked.
 */
export function Launcher() {
  const { user } = useAuth();
  const { apps, error, reload } = useCoreApps();
  const badges = useBadges(apps);
  const [starred, toggleStar] = useStarred(user?.id);
  const { data: links } = useJson<LauncherLink[]>('/api/core/launcher/links'); // failing: no link tiles, apps unaffected
  const openFolder = useSearchParams()[0].get('folder');

  if (error)
    return (
      <div className="mx-auto max-w-5xl px-4 md:px-8">
        <LoadError label="Couldn't load your apps" onRetry={reload} />
      </div>
    );
  if (!apps || !user) return <BootFallback variant="panel" />;

  // The server already filters by role; filtering again keeps a member from ever seeing an
  // admin-only tile if it didn't.
  const tiles = apps.filter((a) => a.roles.includes(user.role) && (!a.hidden || user.role === 'admin'));
  const showStars = tiles.length + (links?.length ?? 0) >= STARS_FROM_TILES;
  const isStarred = (a: CoreApp) => showStars && starred.has(a.slug);

  // The top level holds unfiled apps and one tile per folder, placed where its first app falls.
  // A starred app also shows at the top level, so a star reaches into folders.
  const items: Item[] = [];
  if (openFolder === null) {
    const folders = new Map<string, CoreApp[]>();
    for (const app of tiles) {
      if (!app.folder || isStarred(app)) items.push(app);
      if (!app.folder) continue;
      const group = folders.get(app.folder);
      if (group) group.push(app);
      else {
        folders.set(app.folder, [app]);
        items.push({ folder: app.folder, apps: folders.get(app.folder)! });
      }
    }
  } else items.push(...tiles.filter((a) => a.folder === openFolder));
  // Starred apps first; the sort is stable, so the rest keep the launcher order.
  items.sort((a, b) => Number('slug' in b && isStarred(b)) - Number('slug' in a && isStarred(a)));

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 md:px-8">
      {openFolder === null ? (
        <h1 className="m-0 mb-6 font-display text-2xl font-medium text-sf-ink">Apps</h1>
      ) : (
        <div className="mb-6">
          <Link to="/" className="text-sm text-sf-ink-mute no-underline hover:text-sf-ink">
            ← Apps
          </Link>
          <h1 className="m-0 mt-1 font-display text-2xl font-medium text-sf-ink">{openFolder}</h1>
        </div>
      )}
      {items.length === 0 && (openFolder !== null || !links?.length) ? (
        <p className="text-sf-ink-mute">
          {openFolder === null ? 'No apps are installed for your role yet.' : 'This folder is empty.'}
        </p>
      ) : (
        <ul className="m-0 grid list-none gap-3 p-0 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((item) =>
            'slug' in item ? (
              <AppTile
                key={item.slug}
                app={item}
                badge={badges[item.slug]}
                starred={starred.has(item.slug)}
                onToggleStar={showStars ? () => toggleStar(item.slug) : undefined}
              />
            ) : (
              <FolderTile key={`folder:${item.folder}`} {...item} badges={badges} />
            ),
          )}
          {openFolder === null && (links ?? []).map((link) => <LinkTile key={link.id} link={link} />)}
        </ul>
      )}
    </div>
  );
}

type Item = CoreApp | { folder: string; apps: CoreApp[] };

/** A folder an admin filed apps under; it opens at `/?folder=<name>`. Its badge adds up its apps'. */
function FolderTile({ folder, apps, badges }: { folder: string; apps: CoreApp[]; badges: Record<string, Badge> }) {
  const count = apps.reduce((n, a) => n + (badges[a.slug]?.count ?? 0), 0);
  return (
    <li>
      <Link
        to={`/?${new URLSearchParams({ folder })}`}
        aria-label={`${folder} folder`}
        className="flex h-full items-center gap-3 rounded-lg border border-sf-line-strong bg-sf-card p-4 no-underline hover:border-sf-accent"
      >
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-sf-raised text-sf-ink-mute">
          <AppIcon name="folder" size={22} aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-display text-base font-medium text-sf-ink">{folder}</span>
          <span className="mt-1 line-clamp-1 block text-sm text-sf-ink-soft">{apps.map((a) => a.name).join(', ')}</span>
        </span>
        {count > 0 && (
          <span className="h-fit min-w-6 rounded-full bg-sf-accent px-2 py-0.5 text-center text-xs font-medium text-sf-accent-ink">
            {count}
          </span>
        )}
      </Link>
    </li>
  );
}

/** A tile that opens another site (a connected GTD suite app) in a new tab. */
function LinkTile({ link }: { link: LauncherLink }) {
  return (
    <li>
      <a
        href={link.url}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`${link.title} (opens in a new tab)`}
        className="flex h-full items-center gap-3 rounded-lg border border-sf-line-strong bg-sf-card p-4 no-underline hover:border-sf-accent"
      >
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-sf-raised text-sf-ink-mute">
          <AppIcon name={link.icon} size={22} aria-hidden />
        </span>
        <span className="flex min-w-0 flex-1 items-center gap-2">
          <span className="font-display text-base font-medium text-sf-ink">{link.title}</span>
          {link.hidden && <span className="rounded bg-sf-ink/6 px-1.5 py-0.5 text-xs text-sf-ink-dim">hidden</span>}
        </span>
        <span aria-hidden className="text-sf-ink-dim">
          ↗
        </span>
      </a>
    </li>
  );
}

function AppTile({
  app,
  badge,
  starred,
  onToggleStar,
}: {
  app: CoreApp;
  badge?: Badge;
  starred: boolean;
  /** Absent when the board is too short to show stars. */
  onToggleStar?: () => void;
}) {
  return (
    <li className="relative">
      <Link
        to={app.path}
        aria-label={app.name}
        className={`flex h-full gap-3 rounded-lg border border-sf-line-strong bg-sf-card p-4 no-underline hover:border-sf-accent ${onToggleStar ? 'pb-7' : ''}`}
      >
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
          <span
            title={badge.label ?? undefined}
            aria-label={badge.label ?? `${badge.count} new`}
            className="h-fit min-w-6 rounded-full bg-sf-accent px-2 py-0.5 text-center text-xs font-medium text-sf-accent-ink"
          >
            {badge.count}
          </span>
        )}
      </Link>
      {/* A sibling of the link, not inside it: a button nested in an anchor is invalid HTML. */}
      {onToggleStar && (
        <button
          type="button"
          onClick={onToggleStar}
          aria-pressed={starred}
          aria-label={starred ? `Unstar ${app.name}` : `Star ${app.name}`}
          title={starred ? 'Unstar' : 'Star to keep it at the top'}
          className={`absolute right-3 bottom-2 cursor-pointer border-0 bg-transparent p-0 text-base leading-5 ${starred ? 'text-sf-amber-text' : 'text-sf-ink-dim hover:text-sf-amber-text'}`}
        >
          {starred ? '★' : '☆'}
        </button>
      )}
    </li>
  );
}
