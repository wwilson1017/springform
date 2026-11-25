import { useState } from 'react';
import { patchJson, putJson } from '../api/client';
import type { CoreApp, LauncherLink } from '../api/types';
import { useJson } from '../api/useJson';
import { useCoreApps } from '../apps/CoreAppsContext';
import { useAuth } from '../auth/AuthContext';
import BootFallback from '../components/BootFallback';
import { AppIcon } from '../../shared/icons';
import { toast } from '../../shared/toast';
import { chipClass, errorText, secondaryButtonClass } from './ui';

const arrowClass =
  'cursor-pointer rounded border border-sf-line-strong bg-transparent px-2 py-1 text-xs text-sf-ink-mute hover:bg-sf-hover disabled:cursor-default disabled:opacity-40';

/**
 * Installed apps in launcher order. Admins hide, show, reorder and file them into launcher folders;
 * members see the list.
 * Each write answers with the admin's new app list, shown at once, and reloads the shared list so
 * the header and launcher follow.
 */
export function AppsCard() {
  const { isAdmin } = useAuth();
  const { apps, reload } = useCoreApps();
  const [saved, setSaved] = useState<CoreApp[] | null>(null);
  const [busy, setBusy] = useState(false);
  const links = useJson<LauncherLink[]>('/api/core/launcher/links');
  const list = saved ?? apps;
  if (!list) return <BootFallback variant="panel" />;

  async function write(request: Promise<CoreApp[]>) {
    setBusy(true);
    try {
      setSaved(await request);
      reload();
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function toggleLink(link: LauncherLink) {
    setBusy(true);
    try {
      links.setData(await patchJson<LauncherLink[]>(`/api/core/launcher/links/${link.id}`, { hidden: !link.hidden }));
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  /** Saves a folder name when it changed; a blank one takes the app out of its folder. */
  function fileUnder(app: CoreApp, value: string) {
    if (value.trim() !== (app.folder ?? ''))
      void write(patchJson<CoreApp[]>(`/api/core/apps/${app.slug}`, { folder: value }));
  }

  function move(index: number, by: -1 | 1) {
    const slugs = list!.map((a) => a.slug);
    [slugs[index], slugs[index + by]] = [slugs[index + by], slugs[index]];
    void write(putJson<CoreApp[]>('/api/core/apps/order', { slugs }));
  }

  return (
    <div>
      <ul className="m-0 list-none divide-y divide-sf-line p-0">
        {list.map((app, i) => (
          <li key={app.slug} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5 text-sm">
            <AppIcon name={app.icon} size={18} className="text-sf-ink-mute" aria-hidden />
            <span className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
              <span className="text-sf-ink">{app.name}</span>
              {app.hidden && <span className={chipClass}>Hidden</span>}
              {!isAdmin && app.folder && <span className={chipClass}>{app.folder}</span>}
              {app.badge && (
                <span className={chipClass} title={`Launcher badge from ${app.badge}`}>
                  Badge
                </span>
              )}
            </span>
            {isAdmin && (
              <span className="flex items-center gap-1.5">
                <input
                  key={app.folder ?? ''}
                  defaultValue={app.folder ?? ''}
                  placeholder="No folder"
                  aria-label={`Folder for ${app.name}`}
                  list="launcher-folders"
                  maxLength={40}
                  disabled={busy}
                  onBlur={(e) => fileUnder(app, e.currentTarget.value)}
                  onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
                  className="box-border w-32 rounded-md border border-sf-line-strong bg-sf-card px-2 py-1 text-xs text-sf-ink placeholder:text-sf-ink-dim"
                />
                <button
                  type="button"
                  aria-label={`Move ${app.name} up`}
                  disabled={busy || i === 0}
                  onClick={() => move(i, -1)}
                  className={arrowClass}
                >
                  ↑
                </button>
                <button
                  type="button"
                  aria-label={`Move ${app.name} down`}
                  disabled={busy || i === list.length - 1}
                  onClick={() => move(i, 1)}
                  className={arrowClass}
                >
                  ↓
                </button>
                <button
                  type="button"
                  aria-label={`${app.hidden ? 'Show' : 'Hide'} ${app.name}`}
                  disabled={busy}
                  onClick={() =>
                    void write(patchJson<CoreApp[]>(`/api/core/apps/${app.slug}`, { hidden: !app.hidden }))
                  }
                  className={`${secondaryButtonClass} w-16`}
                >
                  {app.hidden ? 'Show' : 'Hide'}
                </button>
              </span>
            )}
          </li>
        ))}
      </ul>
      <datalist id="launcher-folders">
        {[...new Set(list.map((a) => a.folder).filter(Boolean))].map((f) => (
          <option key={f} value={f!} />
        ))}
      </datalist>
      {!!links.data?.length && (
        <>
          <h3 className="mb-0 mt-5 text-sm font-medium text-sf-ink-soft">Links</h3>
          <ul className="m-0 list-none divide-y divide-sf-line p-0">
            {links.data.map((link) => (
              <li key={link.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5 text-sm">
                <AppIcon name={link.icon} size={18} className="text-sf-ink-mute" aria-hidden />
                <span className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                  <span className="text-sf-ink">{link.title}</span>
                  {link.hidden && <span className={chipClass}>Hidden</span>}
                </span>
                {isAdmin && (
                  <button
                    type="button"
                    aria-label={`${link.hidden ? 'Show' : 'Hide'} ${link.title}`}
                    disabled={busy}
                    onClick={() => void toggleLink(link)}
                    className={`${secondaryButtonClass} w-16`}
                  >
                    {link.hidden ? 'Show' : 'Hide'}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {isAdmin && (
        <p className="mb-0 mt-4 text-xs text-sf-ink-dim">
          A hidden app leaves members' launcher and navigation; admins still see it, marked hidden. The order here is
          the launcher's order for everyone. Type a folder name to file an app into a launcher folder; apps with the
          same name share one folder, and clearing it puts the app back on the main board. Links open another site in a
          new tab.
        </p>
      )}
    </div>
  );
}
