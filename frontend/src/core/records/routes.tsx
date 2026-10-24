import { lazy, type ComponentType } from 'react';
import type { CoreRoute } from '../shell/coreRoutes';

/** A route element whose page chunk loads on first visit. */
function lazyPage(load: () => Promise<{ default: ComponentType }>) {
  const Page = lazy(load);
  return <Page />;
}

export default [
  { path: 'reports', element: lazyPage(() => import('./ReportsPage')) },
  { path: 'reminders', element: lazyPage(() => import('./RemindersPage')) },
  { path: 'notifications', element: lazyPage(() => import('./NotificationsPage')) },
] satisfies CoreRoute[];
