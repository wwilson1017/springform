import { lazy } from 'react';
import type { SettingsSection } from '../settings/settingsSections';

// Eager module, lazy card: the card loads when Settings, GTD suite is opened.
export default [
  {
    id: 'gtd',
    label: 'GTD suite',
    order: 85,
    cards: [
      {
        id: 'gtd',
        title: 'GTD suite',
        adminOnly: true,
        Card: lazy(() => import('./GtdCard')),
      },
    ],
  },
] satisfies SettingsSection[];
