import type { ReactNode } from 'react';
import { Navigate } from 'react-router';
import BootFallback from '../components/BootFallback';
import { NotAllowed } from '../shell/Pages';
import { useAuth } from './AuthContext';

/** Signed-out visitors go to /login. The same spinner as a chunk load while /api/me is in flight. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <BootFallback />;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

/** Members get the Not allowed page, at the URL they asked for. UI gating only: the server refuses the routes regardless. */
export function RequireAdmin({ children }: { children: ReactNode }) {
  const { isAdmin } = useAuth();
  return isAdmin ? children : <NotAllowed />;
}
