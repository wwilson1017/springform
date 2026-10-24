import { Route, Routes } from 'react-router';
import type { AppModule } from '../../core/apps/types';
import { WidgetPage } from './WidgetPage';
import { WidgetsPage } from './WidgetsPage';

/** Mounted by Root under `/example/*`, so these routes are relative to it. */
// eslint-disable-next-line react-refresh/only-export-components -- the contract is a default-exported { slug, App }
function App() {
  return (
    <Routes>
      <Route index element={<WidgetsPage />} />
      <Route path=":id" element={<WidgetPage />} />
      {/* The entity registry's url for a widget (notification and reminder links). */}
      <Route path="widgets/:id" element={<WidgetPage />} />
    </Routes>
  );
}

export default { slug: 'example', App } satisfies AppModule;
