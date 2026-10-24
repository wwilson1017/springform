import { lazy, type ComponentType } from 'react';
import type { CoreRoute } from '../shell/coreRoutes';

/** A lazy screen: its chunk (and react-markdown, for the Guide) loads on first visit, never at boot. */
function page(load: () => Promise<ComponentType>) {
  const Screen = lazy(() => load().then(c => ({ default: c })));
  return <Screen />;
}

export default [
  { path: 'guide', element: page(() => import('./Guide').then(m => m.GuideIndex)) },
  { path: 'guide/:slug', element: page(() => import('./Guide').then(m => m.GuideTopicPage)) },
  { path: 'requests', element: page(() => import('./Requests').then(m => m.RequestsPage)) },
  { path: 'changelog', element: page(() => import('./ChangeLog').then(m => m.ChangeLogPage)) },
  { path: 'jobs', element: page(() => import('./Jobs').then(m => m.JobsPage)), admin: true },
] satisfies CoreRoute[];
