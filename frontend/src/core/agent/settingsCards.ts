import { lazy } from 'react';
import type { SettingsSection } from '../settings/settingsSections';

// Eager module, lazy cards: the AI cards load when Settings, AI is opened.
export default [
  {
    id: 'ai',
    label: 'AI',
    order: 70,
    cards: [
      { id: 'providers', title: 'Providers', adminOnly: true, Card: lazy(() => import('./ProvidersCard')) },
      { id: 'agents', title: 'Agents', adminOnly: true, Card: lazy(() => import('./AgentsCard')) },
      { id: 'memory', title: 'Memory', adminOnly: true, Card: lazy(() => import('./MemoryCard')) },
      { id: 'skills', title: 'Skills', adminOnly: true, Card: lazy(() => import('./SkillsCard')) },
      { id: 'nightly', title: 'Nightly run', adminOnly: true, Card: lazy(() => import('./NightlyCard')) },
      { id: 'web', title: 'Web', adminOnly: true, Card: lazy(() => import('./WebCard')) },
      { id: 'usage', title: 'Usage', adminOnly: true, Card: lazy(() => import('./UsageCard')) },
    ],
  },
] satisfies SettingsSection[];
