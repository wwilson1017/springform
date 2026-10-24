import type { AppModule } from '../../core/apps/types';

/** Placeholder screen until the Todos UI lands; mounted by Root under `/todos/*`. */
// eslint-disable-next-line react-refresh/only-export-components -- the contract is a default-exported { slug, App }
function App() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-10 md:px-7">
      <h1 className="m-0 text-xl font-medium text-sf-ink">Todos</h1>
      <p className="mt-2 text-sm text-sf-ink-mute">The Todos screens are on their way. The API at <code>/api/todos</code> already works.</p>
    </div>
  );
}

export default { slug: 'todos', App } satisfies AppModule;
