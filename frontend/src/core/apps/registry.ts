/**
 * The app registry: the manifests from `virtual:springform-apps` zipped with each app's
 * `contributions.ts` (eager, tiny) and `index.tsx` (lazy). Core reads apps only through here, so
 * adding an app never edits core.
 */
import { lazy, type ComponentType, type LazyExoticComponent } from 'react';
import manifests from 'virtual:springform-apps';
import type { SettingsCardManifest } from '../api/types';
import type { AppContributions, AppManifest, AppModule, NavItem, RecordPanelProps } from './types';

const contributions = import.meta.glob<AppContributions>('../../apps/*/contributions.ts', { eager: true, import: 'default' });
const loaders = import.meta.glob<AppModule>('../../apps/*/index.tsx', { import: 'default' });

export interface RegisteredApp {
  slug: string;
  manifest: AppManifest;
  contributions: AppContributions;
  /** The app's screens; the chunk is fetched the first time its route renders. */
  Screen: LazyExoticComponent<ComponentType>;
}

export interface RegisteredSettingsCard extends SettingsCardManifest {
  slug: string;
  Card: LazyExoticComponent<ComponentType>;
}

export interface RegisteredRecordPanel {
  slug: string;
  entityType: string;
  Panel: LazyExoticComponent<ComponentType<RecordPanelProps>>;
}

// Every lazy() is created here, once, at module load: a lazy() made during render is a new
// component type each time, which remounts its subtree on every render.
export const apps: RegisteredApp[] = manifests.flatMap(manifest => {
  const c = contributions[`../../apps/${manifest.slug}/contributions.ts`];
  const load = loaders[`../../apps/${manifest.slug}/index.tsx`];
  // The vitest contract test fails on a manifest missing either file; at runtime it is skipped.
  if (!c || !load) return [];
  return [{ slug: manifest.slug, manifest, contributions: c, Screen: lazy(() => load().then(m => ({ default: m.App }))) }];
});

const cardsBySlug = new Map(apps.map(app => [
  app.slug,
  (app.manifest.settings_cards ?? []).flatMap(card => {
    const loader = app.contributions.settingsCards?.[card.id];
    return loader ? [{ ...card, slug: app.slug, Card: lazy(loader) }] : [];
  }),
]));

const panels: RegisteredRecordPanel[] = apps.flatMap(app =>
  Object.entries(app.contributions.recordPanels ?? {}).map(([entityType, loader]) => ({ slug: app.slug, entityType, Panel: lazy(loader) })),
);

export const appBySlug = (slug: string): RegisteredApp | undefined => apps.find(a => a.slug === slug);

/** The manifest's settings cards, in manifest order, each with its lazy component. */
export const settingsCardsFor = (slug: string): RegisteredSettingsCard[] => cardsBySlug.get(slug) ?? [];

/** Panels other apps contribute to a record page of this entity type, in app order. */
export const recordPanelsFor = (entityType: string): RegisteredRecordPanel[] => panels.filter(p => p.entityType === entityType);

/** Every app's nav items with the owning slug, so the shell can drop apps the user can't see. */
export const navItems = (): Array<NavItem & { slug: string; icon: string }> =>
  apps.flatMap(app => (app.contributions.nav ?? []).map(item => ({ ...item, slug: app.slug, icon: item.icon ?? app.manifest.icon })));
