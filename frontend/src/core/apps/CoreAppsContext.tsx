import { createContext, useContext, type ReactNode } from 'react';
import type { CoreApp } from '../api/types';
import { useJson } from '../api/useJson';

interface CoreAppsValue {
  /** The caller's apps from GET /api/core/apps (server-filtered by role; admins also get hidden ones). null while loading. */
  apps: CoreApp[] | null;
  error: Error | null;
  reload: () => void;
}

const CoreAppsContext = createContext<CoreAppsValue | null>(null);

/** One fetch of the caller's apps, shared by the header, launcher, settings and app routes. */
export function CoreAppsProvider({ children }: { children: ReactNode }) {
  const { data, error, reload } = useJson<CoreApp[]>('/api/core/apps');
  return <CoreAppsContext.Provider value={{ apps: data, error, reload }}>{children}</CoreAppsContext.Provider>;
}

export function useCoreApps(): CoreAppsValue {
  const ctx = useContext(CoreAppsContext);
  if (!ctx) throw new Error('useCoreApps must be used within CoreAppsProvider');
  return ctx;
}
