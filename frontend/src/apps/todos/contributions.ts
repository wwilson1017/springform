import type { AppContributions } from '../../core/apps/types';

// simplification: placeholder so the backend todos manifest passes the frontend app contract;
// the Todos screens workstream replaces this folder.
export default {
  slug: 'todos',
  settingsCards: { todos: () => import('./SettingsCard') },
} satisfies AppContributions;
