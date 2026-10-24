import type { AppContributions } from '../../core/apps/types';

// Placeholder until the Todos UI lands: it keeps the app contract satisfied (every manifest has
// contributions.ts, every settings card a loader). Lazy loaders and plain data only.
export default {
  slug: 'todos',
  settingsCards: { todos: () => import('./SettingsCard') },
  nav: [{ label: 'Todos', to: '/todos' }],
} satisfies AppContributions;
