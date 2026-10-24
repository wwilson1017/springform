/**
 * Email + password sign-in, plus two routes the server switches on through GET /api/auth/status:
 * "Continue with Google" (a plain form POST, so the server can redirect to Google) and, in
 * PREVIEW_MODE, a role picker over the seed data. A fresh install is sent to /setup.
 *
 * The password form renders even when /api/auth/status fails, with a quiet note: a status blip
 * must not hide the one way in.
 */

import { useEffect, useState, type FormEvent } from 'react';
import { Navigate, useNavigate } from 'react-router';
import { ApiError, fetchJson, postJson } from '../api/client';
import type { AuthStatus, Role } from '../api/types';
import { useAuth } from './AuthContext';
import { AuthLayout, buttonClass, inputClass, labelClass } from './AuthLayout';

function signInError(err: unknown): string {
  if (!(err instanceof ApiError)) return "Can't reach the server. Try again in a moment.";
  if (err.status === 401) return "That email and password don't match an account.";
  if (err.status === 429) return 'Too many attempts. Wait a minute, then try again.';
  return "Couldn't sign in. Try again.";
}

export function LoginPage() {
  const { user, refresh } = useAuth();
  const navigate = useNavigate();
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [statusFailed, setStatusFailed] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchJson<AuthStatus>('/api/auth/status').then(setStatus, () => setStatusFailed(true));
  }, []);

  if (user) return <Navigate to="/" replace />;
  if (status?.setup_required) return <Navigate to="/setup" replace />;

  async function signIn(path: string, body: unknown) {
    setError('');
    setBusy(true);
    try {
      await postJson(path, body);
      // The cookie is set; /api/me is the one source of who that is.
      if (await refresh()) navigate('/', { replace: true });
      else setError("Signed in, but couldn't load your account. Reload the page.");
    } catch (err) {
      setError(signInError(err));
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void signIn('/api/auth/login', { email, password });
  }

  return (
    <AuthLayout subtitle="Sign in to continue.">
      {status?.preview && (
        <div className="mb-8 rounded-md border border-sf-line-strong bg-sf-card p-4">
          <p className="m-0 mb-3 text-sm text-sf-ink-mute">Preview mode: explore the sample data as</p>
          <div className="flex gap-2">
            {(['admin', 'member'] as Role[]).map(role => (
              <button key={role} type="button" disabled={busy}
                onClick={() => void signIn('/api/auth/preview', { role })}
                className="flex-1 cursor-pointer rounded-md border border-sf-line-strong bg-transparent px-3 py-2 text-sm text-sf-ink hover:bg-sf-hover disabled:opacity-50">
                {role === 'admin' ? 'Admin' : 'Member'}
              </button>
            ))}
          </div>
        </div>
      )}

      <form onSubmit={onSubmit}>
        <label htmlFor="login-email" className={labelClass}>Email</label>
        <input id="login-email" type="email" autoComplete="username" value={email}
          onChange={e => setEmail(e.target.value)} placeholder="you@example.com" autoFocus className={inputClass} />
        <label htmlFor="login-password" className={`${labelClass} mt-4`}>Password</label>
        <input id="login-password" type="password" autoComplete="current-password" value={password}
          onChange={e => setPassword(e.target.value)} placeholder="Enter your password" className={inputClass} />
        {error && <p role="alert" className="mb-0 mt-3 text-sm text-sf-red-text">{error}</p>}
        <button type="submit" disabled={busy || !email || !password} className={`${buttonClass} mt-5`}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>

      {status?.google && (
        <form method="post" action="/api/auth/google/start" className="mt-3">
          <button type="submit"
            className="w-full cursor-pointer rounded-md border border-sf-line-strong bg-sf-card px-4 py-3 text-sm font-medium text-sf-ink hover:bg-sf-hover">
            Continue with Google
          </button>
        </form>
      )}

      {statusFailed && (
        <p className="mt-6 text-center text-xs text-sf-ink-dim">
          Can't reach the server right now, so some sign-in options may be missing.
        </p>
      )}
    </AuthLayout>
  );
}
