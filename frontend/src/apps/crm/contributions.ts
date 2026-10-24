import type { AppContributions } from '../../core/apps/types';

// Loaded eagerly into the shell: lazy loaders and plain data only, never a static screen import.
export default {
  slug: 'crm',
  settingsCards: { crm: () => import('./SettingsCard') },
  recordPanels: {
    'core.person': () => import('./DealsPanel'),
    'core.organization': () => import('./DealsPanel'),
  },
  nav: [{ label: 'CRM', to: '/crm' }],
} satisfies AppContributions;
