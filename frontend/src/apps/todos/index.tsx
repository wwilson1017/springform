import { useCallback } from 'react';
import { Navigate, Route, Routes } from 'react-router';
import type { AppModule } from '../../core/apps/types';
import { useAuth } from '../../core/auth/AuthContext';
import { AreasPage } from './AreasPage';
import { DonePage } from './DonePage';
import { InboxPage } from './InboxPage';
import { ItemPage } from './ItemPage';
import { MeContext } from './me';
import { TODOS_ROOT } from './menu';
import { NextActionsPage } from './NextActionsPage';
import { ProjectDetailPage } from './ProjectDetailPage';
import { ProjectsPage } from './ProjectsPage';
import { ReviewPage } from './ReviewPage';
import { SearchPage } from './SearchPage';
import { SomedayPage } from './SomedayPage';
import { useChangeFeed } from './sync';
import { TodayPage } from './TodayPage';
import { refreshMeta } from './useTodoMeta';
import { WaitingPage } from './WaitingPage';

/** Mounted by Root under `/todos/*` inside the core Layout, so these routes are relative to it.
 *  Today is the app's home. The change feed runs here, once, rather than in the per-page shell. */
// eslint-disable-next-line react-refresh/only-export-components -- the contract is a default-exported { slug, App }
function App() {
  const { user, isAdmin } = useAuth();
  const onBatch = useCallback(() => { void refreshMeta(); }, []);
  useChangeFeed(String(user?.id ?? ''), onBatch);
  return (
    <MeContext.Provider value={{ id: user?.id ?? null, isAdmin }}>
      <Routes>
        <Route index element={<TodayPage />} />
        <Route path="today" element={<Navigate to={TODOS_ROOT} replace />} />
        <Route path="inbox" element={<InboxPage />} />
        <Route path="next" element={<NextActionsPage />} />
        <Route path="waiting" element={<WaitingPage />} />
        <Route path="someday" element={<SomedayPage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:id" element={<ProjectDetailPage />} />
        <Route path="areas" element={<AreasPage />} />
        <Route path="review" element={<ReviewPage />} />
        <Route path="done" element={<DonePage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="items/:id" element={<ItemPage />} />
        {/* Anything else stays inside the app. */}
        <Route path="*" element={<Navigate to={TODOS_ROOT} replace />} />
      </Routes>
    </MeContext.Provider>
  );
}

export default { slug: 'todos', App } satisfies AppModule;
