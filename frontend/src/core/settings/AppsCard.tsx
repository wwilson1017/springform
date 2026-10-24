import { AppIcon } from '../../shared/icons';
import { useCoreApps } from '../apps/CoreAppsContext';

/** Installed apps in launcher order with their visibility. Display only for now. */
export function AppsCard() {
  const { apps } = useCoreApps();
  return (
    <div>
      <ul className="m-0 list-none divide-y divide-sf-line p-0">
        {(apps ?? []).map(app => (
          <li key={app.slug} className="flex items-center gap-3 py-2.5 text-sm">
            <AppIcon name={app.icon} size={18} className="text-sf-ink-mute" aria-hidden />
            <span className="flex-1 text-sf-ink">{app.name}</span>
            <span className="text-xs text-sf-ink-dim">order {app.order}</span>
            <span className="w-14 text-right text-xs text-sf-ink-soft">{app.hidden ? 'Hidden' : 'Shown'}</span>
          </li>
        ))}
      </ul>
      <p className="mb-0 mt-4 text-xs text-sf-ink-dim">Hiding and reordering apps arrive in the next wave.</p>
    </div>
  );
}
