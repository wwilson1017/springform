import { Route, Routes } from 'react-router';
import type { AppModule } from '../../core/apps/types';
import { WidgetPage } from './WidgetPage';
import { WidgetsPage } from './WidgetsPage';

/** Mounted by Root under `/example/*`, so these routes are relative to it. */
function App() {
  return (
    <Routes>
      <Route index element={<WidgetsPage />} />
      {/* Also the entity registry's url for a widget (notification and reminder links). */}
      <Route path=":id" element={<WidgetPage />} />
    </Routes>
  );
}

export default { slug: 'example', App } satisfies AppModule;
