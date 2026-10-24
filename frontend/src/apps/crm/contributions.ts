import type { AppContributions } from '../../core/apps/types';

// Placeholder until the CRM UI lands: it keeps the app contract satisfied (every manifest has
// contributions.ts, every settings card a loader). Lazy loaders and plain data only.
export default {
  slug: 'crm',
  settingsCards: { crm: () => import('./SettingsCard') },
  nav: [{ label: 'CRM', to: '/crm' }],
} satisfies AppContributions;
