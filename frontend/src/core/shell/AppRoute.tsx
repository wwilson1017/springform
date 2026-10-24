import { useCoreApps } from '../apps/CoreAppsContext';
import type { RegisteredApp } from '../apps/registry';
import BootFallback from '../components/BootFallback';
import { LoadError } from '../../shared/LoadError';
import { NotFound } from './Pages';

/**
 * An app's route. Every installed app has one, but it renders only for apps the server lists for
 * this user (GET /api/core/apps applies the role filter); anyone else gets the 404. The Layout's
 * Suspense and route boundary cover the lazy chunk.
 */
export function AppRoute({ app }: { app: RegisteredApp }) {
  const { apps, error, reload } = useCoreApps();
  if (error) return <div className="mx-auto max-w-5xl px-4 md:px-8"><LoadError onRetry={reload} /></div>;
  if (!apps) return <BootFallback variant="panel" />;
  if (!apps.some(a => a.slug === app.slug)) return <NotFound />;
  return <app.Screen />;
}
