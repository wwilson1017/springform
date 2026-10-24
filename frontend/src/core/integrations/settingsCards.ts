import { lazy } from 'react';
import type { SettingsSection } from '../settings/settingsSections';

export default [
  {
    id: 'integrations', label: 'Integrations', order: 50, cards: [
      { id: 'github', title: 'GitHub', adminOnly: true, Card: lazy(() => import('./GitHubCard')) },
      { id: 'sheets', title: 'Google Sheets', adminOnly: true, Card: lazy(() => import('./SheetsCard')) },
    ],
  },
] satisfies SettingsSection[];
