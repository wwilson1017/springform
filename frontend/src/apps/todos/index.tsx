import type { AppModule } from '../../core/apps/types';

/** Placeholder until the Todos screens land; the API is live at /api/todos. */
// eslint-disable-next-line react-refresh/only-export-components -- the contract is a default-exported { slug, App }
function App() {
  return <p className="m-0 p-6 text-sm text-sf-ink-mute">Todos screens are coming soon.</p>;
}

export default { slug: 'todos', App } satisfies AppModule;
