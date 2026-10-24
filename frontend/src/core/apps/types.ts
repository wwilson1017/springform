import type { ComponentType } from 'react';
import type { Role, SettingsCard } from '../api/types';

/** `backend/apps/<slug>/app.json`, as `virtual:springform-apps` serves it (see vite-plugin-apps.ts). */
export interface AppManifest {
  slug: string;
  name: string;
  description: string;
  path: string;
  icon: string;
  roles: Role[];
  order: number;
  badge?: string | null;
  docs?: string;
  version: string;
  requires_core?: string;
  settings_cards?: SettingsCard[];
  sheets?: Array<{ name: string; mode: string; description: string }>;
  publishes?: string[];
}

/** A code-split component: `() => import('./SettingsCard')`. */
export type LazyComponent<P = object> = () => Promise<{ default: ComponentType<P> }>;

export interface RecordPanelProps {
  entityType: string;
  entityId: number;
}

export interface NavItem {
  label: string;
  /** Absolute path, normally the app's own `path` or below it. */
  to: string;
  /** An icon name as in the manifest; defaults to the app's icon. */
  icon?: string;
}

/**
 * The default export of `src/apps/<slug>/contributions.ts`. It is loaded EAGERLY into the shell,
 * so it holds only lazy loaders and plain data, never screen code (the bootSplit test enforces
 * this and a 2 KB ceiling).
 */
export interface AppContributions {
  slug: string;
  /** Keyed by the manifest's `settings_cards[].id`; one loader per card. */
  settingsCards?: Record<string, LazyComponent>;
  /** Keyed by entity type (`core.person`, `core.organization`); shown on that record's page. */
  recordPanels?: Record<string, LazyComponent<RecordPanelProps>>;
  nav?: NavItem[];
}

/**
 * The default export of `src/apps/<slug>/index.tsx`, loaded only when the app's route is visited.
 * Root mounts `App` under `<Route path="<path>/*">`, so `App` renders relative `<Routes>`.
 */
export interface AppModule {
  slug: string;
  App: ComponentType;
}
