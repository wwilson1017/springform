/**
 * `/reset-password/:token`: choose a new password from a forgot-password link. The link works
 * once, for an hour; a used or expired one answers 404 on submit. A reset ends every other
 * session and forgets trusted browsers, so a user with 2FA goes through the challenge step.
 */

import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { postJson } from '../api/client';
import { AuthLayout, buttonClass, inputClass, labelClass } from './AuthLayout';
import { errorText, type LoginResult } from './api';
import { ChallengeStep } from './ChallengeStep';
import { useSignIn } from './useSignIn';

export default function ResetPasswordPage() {
  const token = useParams().token ?? '';
  const navigate = useNavigate();
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
      setError(await finish(await postJson<LoginResult>('/api/auth/reset', { token, password })));
    } catch (err) {
      setError(errorText(err, {
        not_found: 'This reset link has expired or was already used. Ask for a new one from the sign-in page.',
      }, "Couldn't reset your password. Try again."));
    } finally {
      setBusy(false);
    }
  }

  if (challenge) {
    return (
      <AuthLayout subtitle="One more step.">
        <ChallengeStep challenge={challenge} onSignedIn={enter}
          onRestart={message => navigate('/login', { replace: true, state: { notice: message || 'Your new password is saved. Sign in with it.' } })} />
      </AuthLayout>
    );
  }

  return (
    <AuthLayout subtitle="Choose a new password.">
      <form onSubmit={onSubmit}>
        <label htmlFor="reset-password" className={labelClass}>New password</label>
        <input id="reset-password" type="password" autoComplete="new-password" value={password} autoFocus
          onChange={e => setPassword(e.target.value)} placeholder="At least 8 characters" className={inputClass} />
        <label htmlFor="reset-confirm" className={`${labelClass} mt-4`}>Confirm password</label>
        <input id="reset-confirm" type="password" autoComplete="new-password" value={confirm} aria-invalid={mismatch}
          onChange={e => setConfirm(e.target.value)} className={inputClass} />
        {mismatch && <p className="mb-0 mt-2 text-xs text-sf-red-text">Passwords don't match.</p>}
        {error && <p role="alert" className="mb-0 mt-3 text-sm text-sf-red-text">{error}</p>}
        <button type="submit" disabled={busy || password.length < 8 || password !== confirm} className={`${buttonClass} mt-5`}>
          {busy ? 'Saving…' : 'Save and sign in'}
        </button>
      </form>
      <p className="mb-0 mt-6 text-center text-sm"><Link to="/login" className="text-sf-accent-text">Back to sign in</Link></p>
    </AuthLayout>
  );
}
