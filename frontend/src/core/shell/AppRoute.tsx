import type { RegisteredApp } from '../apps/registry';
import { useAuth } from '../auth/AuthContext';
import { NotFound } from './Pages';

/**
 * An app's route. Every installed app has one; it renders for users whose role the manifest
 * lists, and anyone else gets the 404 (the server refuses the app's API regardless).
 *
 * The role check reads the manifest rather than GET /api/core/apps on purpose: hiding an app
 * removes its tile and nav for members, but its URL stays reachable, and members are not sent
 * hidden apps at all. The Layout's Suspense and route boundary cover the lazy chunk.
 */
export function AppRoute({ app }: { app: RegisteredApp }) {
  const { user } = useAuth();
  if (!user || !app.manifest.roles.includes(user.role)) return <NotFound />;
  return <app.Screen />;
}
