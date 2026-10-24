/**
 * Sign-in. Email + password, then the 2FA step when the account has it on. GET /api/auth/status
 * switches on "Continue with Google" (a plain link: the server redirects to Google) and, in
 * PREVIEW_MODE, a role picker over the seed data. A fresh install is sent to /setup.
 *
 * The Google callback lands here with `?error=<code>` when it refuses, or with
 * `#totp_challenge=<token>` when the install requires 2FA after Google too. "Forgot password?"
 * is a mode of this page; its answer never says whether the account exists.
 *
 * The password form renders even when /api/auth/status fails, with a quiet note: a status blip
 * must not hide the one way in.
 */

import { useEffect, useState, type FormEvent } from 'react';
import { Navigate, useLocation, useNavigate, useSearchParams } from 'react-router';
import { fetchJson, postJson } from '../api/client';
import type { AuthStatus, Role } from '../api/types';
import { useAuth } from './AuthContext';
import { AuthLayout, buttonClass, inputClass, labelClass } from './AuthLayout';
import { btnLink, errorText, GOOGLE_ERRORS, type LoginResult } from './api';
import { ChallengeStep } from './ChallengeStep';
import { useSignIn } from './useSignIn';

const SIGN_IN_ERRORS = { invalid_credentials: "That email and password don't match an account." };

/** The challenge the Google callback hands over in the fragment, kept out of server logs. */
const fragmentChallenge = (hash: string) => new URLSearchParams(hash.replace(/^#/, '')).get('totp_challenge');

export function LoginPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const { challenge, setChallenge, finish, enter } = useSignIn(fragmentChallenge(location.hash));
  const [mode, setMode] = useState<'password' | 'forgot'>('password');
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [statusFailed, setStatusFailed] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const errorCode = params.get('error');
  const [notice, setNotice] = useState<string>(
    errorCode ? GOOGLE_ERRORS[errorCode] ?? "Sign-in didn't finish. Try again." : (location.state as { notice?: string } | null)?.notice ?? '',
  );

  useEffect(() => {
    fetchJson<AuthStatus>('/api/auth/status').then(setStatus, () => setStatusFailed(true));
  }, []);

  // The challenge is in state now; take it out of the address bar and history.
  useEffect(() => {
    if (location.hash) navigate({ pathname: location.pathname, search: location.search }, { replace: true });
  }, [location.hash, location.pathname, location.search, navigate]);

  if (user) return <Navigate to="/" replace />;
  if (status?.setup_required) return <Navigate to="/setup" replace />;

  async function signIn(path: string, body: unknown) {
    setError('');
    setNotice('');
    setBusy(true);
    try {
      setError(await finish(await postJson<LoginResult>(path, body)));
    } catch (err) {
      setError(errorText(err, SIGN_IN_ERRORS, "Couldn't sign in. Try again."));
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void signIn('/api/auth/login', { email, password });
  }

  if (challenge) {
    return (
      <AuthLayout subtitle="One more step.">
        <ChallengeStep challenge={challenge} onSignedIn={enter}
          onRestart={message => { setChallenge(null); setPassword(''); setError(message); }} />
      </AuthLayout>
    );
  }

  if (mode === 'forgot') {
    return (
      <AuthLayout subtitle="Reset your password.">
        <ForgotForm initialEmail={email} onBack={() => setMode('password')} />
      </AuthLayout>
    );
  }

  return (
    <AuthLayout subtitle="Sign in to continue.">
      {notice && <p role="alert" className="mb-6 mt-0 text-sm text-sf-red-text">{notice}</p>}
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
        <div className="mt-4 flex items-baseline justify-between">
          <label htmlFor="login-password" className={labelClass}>Password</label>
          <button type="button" className={`${btnLink} text-xs`} onClick={() => { setError(''); setNotice(''); setMode('forgot'); }}>
            Forgot password?
          </button>
        </div>
        <input id="login-password" type="password" autoComplete="current-password" value={password}
          onChange={e => setPassword(e.target.value)} placeholder="Enter your password" className={inputClass} />
        {error && <p role="alert" className="mb-0 mt-3 text-sm text-sf-red-text">{error}</p>}
        <button type="submit" disabled={busy || !email || !password} className={`${buttonClass} mt-5`}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>

      {status?.google && <GoogleButton href="/api/auth/google/start" />}

      {statusFailed && (
        <p className="mt-6 text-center text-xs text-sf-ink-dim">
          Can't reach the server right now, so some sign-in options may be missing.
        </p>
      )}
    </AuthLayout>
  );
}

/** A top-level navigation, not fetch: the server answers with a redirect to Google. */
export function GoogleButton({ href }: { href: string }) {
  return (
    <a href={href}
      className="mt-3 box-border block w-full rounded-md border border-sf-line-strong bg-sf-card px-4 py-3 text-center text-sm font-medium text-sf-ink no-underline hover:bg-sf-hover">
      Continue with Google
    </a>
  );
}

function ForgotForm({ initialEmail, onBack }: { initialEmail: string; onBack: () => void }) {
  const [email, setEmail] = useState(initialEmail);
  const [sent, setSent] = useState<{ mail: boolean } | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      setSent(await postJson<{ mail: boolean }>('/api/auth/forgot', { email }));
    } catch (err) {
      setError(errorText(err, {}, "Couldn't send the request. Try again."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      {sent ? (
        // The same answer whether or not the account exists.
        <p role="status" className="m-0 text-sm text-sf-ink">
          {sent.mail
            ? 'If an account uses that email, a reset link is on its way. It works for an hour.'
            : "This install can't send email, so no reset link was sent. Ask an admin to help you back in."}
        </p>
      ) : (
        <form onSubmit={onSubmit}>
          <p className="mb-5 mt-0 text-sm text-sf-ink-mute">Enter your email and we'll send you a link to choose a new password.</p>
          <label htmlFor="forgot-email" className={labelClass}>Email</label>
          <input id="forgot-email" type="email" autoComplete="username" value={email} autoFocus
            onChange={e => setEmail(e.target.value)} placeholder="you@example.com" className={inputClass} />
          {error && <p role="alert" className="mb-0 mt-3 text-sm text-sf-red-text">{error}</p>}
          <button type="submit" disabled={busy || !email.trim()} className={`${buttonClass} mt-5`}>
            {busy ? 'Sending…' : 'Send reset link'}
          </button>
        </form>
      )}
      <p className="mb-0 mt-6 text-center text-sm">
        <button type="button" className={btnLink} onClick={onBack}>Back to sign in</button>
      </p>
    </div>
  );
}
