/**
 * Who is signed in. The session is an HttpOnly cookie, so the browser holds no token: the
 * answer always comes from GET /api/me, which reads the live user row (a demotion shows on the
 * next request, not at session expiry). That is also why `role` is read from here.
 *
 * Sign-in itself is done by the login, setup and preview pages; each then calls `refresh()`.
 */

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import type { User } from '../api/types';

interface AuthContextValue {
  user: User | null;
  /** True until the first /api/me answer. */
  loading: boolean;
  /** For hiding admin-only UI. The server gates the routes regardless. */
  isAdmin: boolean;
  /** Re-read /api/me; returns the user, or null when signed out or unreachable. */
  refresh: () => Promise<User | null>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * A 401 means signed out. Anything else that fails (a 502 mid-deploy, a network drop) also
 * lands the user on /login, where the page says the server can't be reached; with a cookie
 * session there is nothing to discard, so one reload restores them once it is back.
 * Plain fetch, not `fetchJson`: a 401 here is the answer, not a reason to redirect.
 */
async function fetchMe(): Promise<User | null> {
  try {
    const res = await fetch('/api/me', { credentials: 'same-origin' });
    return res.ok ? ((await res.json()) as User) : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const me = await fetchMe();
    setUser(me);
    setLoading(false);
    return me;
  }, []);

  // The first answer. Inline rather than `refresh()` so the setState lands in a callback.
  useEffect(() => {
    fetchMe().then(me => { setUser(me); setLoading(false); });
  }, []);

  const signOut = useCallback(async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
    } catch { /* the cookie may survive an unreachable server; clearing local state still signs this tab out */ }
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, isAdmin: user?.role === 'admin', refresh, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
