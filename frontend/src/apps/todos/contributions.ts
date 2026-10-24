import type { AppContributions } from '../../core/apps/types';

// Loaded eagerly into the shell: lazy loaders and plain data only, never a static screen import.
export default {
  slug: 'todos',
  settingsCards: { todos: () => import('./SettingsCard') },
  recordPanels: {
    'core.person': () => import('./RecordPanel'),
    'core.organization': () => import('./RecordPanel'),
  },
  nav: [{ label: 'Todos', to: '/todos' }],
} satisfies AppContributions;
