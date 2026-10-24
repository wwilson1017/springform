import { Suspense } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router';
import { ConfirmHost } from '../shared/ConfirmHost';
import { ToastViewport } from '../shared/ToastViewport';
import { CoreAppsProvider } from './apps/CoreAppsContext';
import { apps } from './apps/registry';
import { AuthProvider } from './auth/AuthContext';
import { RequireAdmin, RequireAuth } from './auth/guards';
import { LoginPage } from './auth/LoginPage';
import { SetupPage } from './auth/SetupPage';
import BootFallback from './components/BootFallback';
import ChunkErrorBoundary from './components/ChunkErrorBoundary';
import { SettingsPage } from './settings/SettingsPage';
import { AppRoute } from './shell/AppRoute';
import { coreRoutes } from './shell/coreRoutes';
import { Launcher } from './shell/Launcher';
import { Layout } from './shell/Layout';
import { NotFound } from './shell/Pages';

/**
 * The composition root. The core shell is eager (it is small and every signed-in visit needs
 * it); each app's screens are lazy and fetched on first visit to `<path>/*`. One route per
 * installed app comes from the registry; `AppRoute` shows it only to users the server lists it
 * for. `src/bootSplit.test.ts` fails if an app's screens reach the entry chunk.
 *
 * The toast and confirm hosts sit outside the Suspense boundary so a chunk load never replaces
 * an open dialog or a toast in flight.
 */
export default function Root() {
  return (
    <ChunkErrorBoundary>
      <BrowserRouter>
        <AuthProvider>
          <Suspense fallback={<BootFallback />}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/setup" element={<SetupPage />} />
              {coreRoutes('public').map(r => <Route key={r.path} path={r.path} element={r.element} />)}
              <Route element={<RequireAuth><CoreAppsProvider><Layout /></CoreAppsProvider></RequireAuth>}>
                <Route index element={<Launcher />} />
                <Route path="settings/*" element={<SettingsPage />} />
                {coreRoutes('shell').map(r => (
                  <Route key={r.path} path={r.path} element={r.admin ? <RequireAdmin>{r.element}</RequireAdmin> : r.element} />
                ))}
                {apps.map(app => (
                  <Route key={app.slug} path={`${app.manifest.path}/*`} element={<AppRoute app={app} />} />
                ))}
                <Route path="*" element={<NotFound />} />
              </Route>
            </Routes>
          </Suspense>
          <ConfirmHost />
          <ToastViewport />
        </AuthProvider>
      </BrowserRouter>
    </ChunkErrorBoundary>
  );
}
