import { lazy } from 'react';
import { AppsCard } from './AppsCard';
import type { SettingsSection } from './settingsSections';
import { WorkspaceCard } from './WorkspaceCard';

// The shell's own core settings sections; other core areas add theirs in their own
// `settingsCards.ts` (see settingsSections.ts).
export default [
  { id: 'workspace', label: 'Workspace', order: 10, cards: [{ id: 'workspace', title: 'Workspace', adminOnly: false, Card: WorkspaceCard }] },
  { id: 'apps', label: 'Apps', order: 20, cards: [{ id: 'apps', title: 'Apps', adminOnly: false, Card: AppsCard }] },
  {
    id: 'data', label: 'Data', order: 60, cards: [
      { id: 'export', title: 'Export', adminOnly: true, Card: lazy(() => import('./ExportCard')) },
      { id: 'files', title: 'Files', adminOnly: true, Card: lazy(() => import('./FilesCard')) },
    ],
  },
] satisfies SettingsSection[];
