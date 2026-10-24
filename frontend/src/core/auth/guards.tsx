import type { ReactNode } from 'react';
import { Navigate } from 'react-router';
import BootFallback from '../components/BootFallback';
import { useAuth } from './AuthContext';

/** Signed-out visitors go to /login. The same spinner as a chunk load while /api/me is in flight. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <BootFallback />;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

/** Members are sent to `fallback`. UI gating only: the server refuses the routes regardless. */
export function RequireAdmin({ children, fallback = '/' }: { children: ReactNode; fallback?: string }) {
  const { isAdmin } = useAuth();
  return isAdmin ? children : <Navigate to={fallback} replace />;
}
