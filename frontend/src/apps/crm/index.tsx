import { Route, Routes } from 'react-router';
import type { AppModule } from '../../core/apps/types';
import { NotFound } from '../../core/shell/Pages';
import { CrmNav } from './components/CrmNav';
import { AnalyticsPage } from './pages/AnalyticsPage';
import { DashboardPage } from './pages/DashboardPage';
import { DealDetailPage } from './pages/DealDetailBody';
import { ImportPage } from './pages/ImportPage';
import { PipelinePage } from './pages/PipelinePage';
import { StalePage } from './pages/StalePage';
import { TodayPage } from './pages/TodayPage';
import { TouchDetailPage } from './pages/TouchDetailPage';
import { TouchesPage } from './pages/TouchesPage';
import './theme.css';

/** Mounted by Root under `/crm/*`, so these routes are relative to it. */
// eslint-disable-next-line react-refresh/only-export-components -- the contract is a default-exported { slug, App }
function App() {
  return (
    <>
      <CrmNav />
      <Routes>
        <Route index element={<DashboardPage />} />
        <Route path="deals" element={<PipelinePage />} />
        <Route path="deals/:id" element={<DealDetailPage />} />
        <Route path="today" element={<TodayPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="touches" element={<TouchesPage />} />
        <Route path="touches/:owner" element={<TouchDetailPage />} />
        <Route path="stale" element={<StalePage />} />
        <Route path="import" element={<ImportPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </>
  );
}

export default { slug: 'crm', App } satisfies AppModule;
