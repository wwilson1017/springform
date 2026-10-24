/**
 * `/invite/:token`: accept an invite by choosing a password or with "Continue with Google"
 * (which links whichever Google account is picked: the link proved the mailbox). An expired or
 * used link answers 404. The Google callback comes back here with `?error=<code>` on failure.
 */

import { useEffect, useState, type FormEvent } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { ApiError, fetchJson, postJson } from '../api/client';
import { useAuth } from './AuthContext';
import { AuthLayout, buttonClass, inputClass, labelClass } from './AuthLayout';
import { errorText, GOOGLE_ERRORS, type LoginResult } from './api';
import { ChallengeStep } from './ChallengeStep';
import { GoogleButton } from './LoginPage';
import { useSignIn } from './useSignIn';

interface Invite {
  email: string;
  name: string;
  google: boolean;
}

export default function InvitePage() {
  const token = useParams().token ?? '';
  const errorCode = useSearchParams()[0].get('error');
  const [invite, setInvite] = useState<Invite | null>(null);
  const [lookup, setLookup] = useState<'loading' | 'ok' | 'gone' | 'failed'>('loading');

  useEffect(() => {
    fetchJson<Invite>(`/api/auth/invite/${encodeURIComponent(token)}`).then(
      i => { setInvite(i); setLookup('ok'); },
      err => setLookup(err instanceof ApiError && err.status === 404 ? 'gone' : 'failed'),
    );
  }, [token]);

  if (lookup === 'loading') return <AuthLayout subtitle="Checking your invite…">{null}</AuthLayout>;
  if (lookup !== 'ok' || !invite) {
    return (
      <AuthLayout subtitle={lookup === 'gone' ? 'This link has expired.' : "Can't reach the server."}>
        <p className="mt-0 text-center text-sm text-sf-ink-mute">
          {lookup === 'gone'
            ? 'Invite links work once, for an hour. Ask an admin to send you a new one.'
            : 'Try again in a moment.'}
        </p>
        <p className="mb-0 mt-6 text-center text-sm"><Link to="/login" className="text-sf-accent-text">Go to sign in</Link></p>
      </AuthLayout>
    );
  }
  return <AcceptForm token={token} invite={invite} notice={errorCode ? GOOGLE_ERRORS[errorCode] ?? GOOGLE_ERRORS.google_failed : ''} />;
}

function AcceptForm({ token, invite, notice }: { token: string; invite: Invite; notice: string }) {
  const { user } = useAuth();
  const { challenge, finish, enter } = useSignIn();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const mismatch = confirm.length > 0 && password !== confirm;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      setError(await finish(await postJson<LoginResult>(`/api/auth/invite/${encodeURIComponent(token)}`, { password })));
    } catch (err) {
      setError(errorText(err, { not_found: 'This invite link has expired. Ask an admin to send a new one.' }, "Couldn't set your password. Try again."));
    } finally {
      setBusy(false);
    }
  }

  if (challenge) {
    return (
      <AuthLayout subtitle="One more step.">
        {/* The password is saved by now, so starting over means signing in with it. */}
        <ChallengeStep challenge={challenge} onSignedIn={enter} onRestart={() => window.location.assign('/login')} />
      </AuthLayout>
    );
  }

  return (
    <AuthLayout subtitle={`Welcome${invite.name ? `, ${invite.name}` : ''}. Set up your account.`}>
      {notice && <p role="alert" className="mb-6 mt-0 text-sm text-sf-red-text">{notice}</p>}
      {user && user.email !== invite.email && (
        <p className="mb-6 mt-0 text-sm text-sf-ink-mute">
          You're signed in as {user.email}. Accepting this invite signs you in as {invite.email} instead.
        </p>
      )}
      <form onSubmit={onSubmit}>
        <p className={labelClass}>Email</p>
        <p className="m-0 mb-4 break-all text-base text-sf-ink">{invite.email}</p>
        <label htmlFor="invite-password" className={labelClass}>Choose a password</label>
        <input id="invite-password" type="password" autoComplete="new-password" value={password} autoFocus
          onChange={e => setPassword(e.target.value)} placeholder="At least 8 characters" className={inputClass} />
        <label htmlFor="invite-confirm" className={`${labelClass} mt-4`}>Confirm password</label>
        <input id="invite-confirm" type="password" autoComplete="new-password" value={confirm} aria-invalid={mismatch}
          onChange={e => setConfirm(e.target.value)} className={inputClass} />
        {mismatch && <p className="mb-0 mt-2 text-xs text-sf-red-text">Passwords don't match.</p>}
        {error && <p role="alert" className="mb-0 mt-3 text-sm text-sf-red-text">{error}</p>}
        <button type="submit" disabled={busy || password.length < 8 || password !== confirm} className={`${buttonClass} mt-5`}>
          {busy ? 'Setting up…' : 'Set password and sign in'}
        </button>
      </form>
      {invite.google && (
        <>
          <p className="my-4 text-center text-xs text-sf-ink-dim">or</p>
          <GoogleButton href={`/api/auth/google/start?invite=${encodeURIComponent(token)}`} />
        </>
      )}
    </AuthLayout>
  );
}
