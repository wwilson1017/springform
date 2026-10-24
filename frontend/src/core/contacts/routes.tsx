import { lazy, type ComponentType } from 'react';
import type { CoreRoute } from '../shell/coreRoutes';
import type { ContactKind } from './types';

/**
 * A lazy page per route, so the directory stays out of the shell's entry chunk. Each route gets
 * its own component type, so moving between /people and /organizations mounts a fresh page
 * instead of reusing one that still holds the other kind's state.
 */
function screen(load: () => Promise<{ default: ComponentType<{ kind: ContactKind }> }>, kind: ContactKind) {
  const Screen = lazy(load);
  return <Screen kind={kind} />;
}

export default [
  { path: 'people', element: screen(() => import('./ListPage'), 'person') },
  { path: 'people/:id', element: screen(() => import('./DetailPage'), 'person') },
  { path: 'organizations', element: screen(() => import('./ListPage'), 'organization') },
  { path: 'organizations/:id', element: screen(() => import('./DetailPage'), 'organization') },
] satisfies CoreRoute[];
