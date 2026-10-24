import type { AppModule } from '../../core/apps/types';

/** Placeholder screen until the CRM UI lands; mounted by Root under `/crm/*`. */
// eslint-disable-next-line react-refresh/only-export-components -- the contract is a default-exported { slug, App }
function App() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-10 md:px-7">
      <h1 className="m-0 text-xl font-medium text-sf-ink">CRM</h1>
      <p className="mt-2 text-sm text-sf-ink-mute">The CRM screens are on their way. The API at <code>/api/crm</code> already works.</p>
    </div>
  );
}

export default { slug: 'crm', App } satisfies AppModule;
