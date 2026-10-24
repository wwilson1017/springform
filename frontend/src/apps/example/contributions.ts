import type { AppContributions } from '../../core/apps/types';

// Loaded eagerly into the shell: lazy loaders and plain data only, never a static screen import.
export default {
  slug: 'example',
  settingsCards: { example: () => import('./SettingsCard') },
  recordPanels: { 'core.person': () => import('./PersonPanel') },
  nav: [{ label: 'Example', to: '/example' }],
} satisfies AppContributions;
