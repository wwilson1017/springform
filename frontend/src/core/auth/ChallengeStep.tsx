/**
 * The second sign-in step for a user with 2FA on: an authenticator code or a backup code for the
 * `challenge` the first factor returned (a 5-minute token). Shared by the login, invite and
 * reset pages. "Trust this browser" skips the step here for 30 days.
 */

import { useState, type FormEvent } from 'react';
import { ApiError, postJson } from '../api/client';
import { btnLink, errorText } from './api';
import { buttonClass, inputClass } from './AuthLayout';

interface Props {
  challenge: string;
  /** After the cookie is set: load the user and go home. Returns an error message or ''. */
  onSignedIn: () => Promise<string>;
  /** The challenge expired or was refused: start over, with this message. */
  onRestart: (message: string) => void;
}

export function ChallengeStep({ challenge, onSignedIn, onRestart }: Props) {
  const [code, setCode] = useState('');
  const [backup, setBackup] = useState(false);
  const [trust, setTrust] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const given = code.trim();
      await postJson('/api/auth/login/totp', { challenge, trust_device: trust, ...(backup ? { backup_code: given } : { code: given }) });
      setError(await onSignedIn());
    } catch (err) {
      if (err instanceof ApiError && err.detail === 'challenge_expired') {
        onRestart('That took too long, so the sign-in expired. Start again.');
        return;
      }
      setCode('');
      setError(errorText(err, {
        invalid_code: backup ? "That backup code didn't work, or it was already used." : "That code didn't work. Enter the newest one from your app.",
      }, "Couldn't check the code. Try again."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit}>
      <h2 className="m-0 mb-1 font-display text-xl font-medium text-sf-ink">Two-factor authentication</h2>
      <p className="mb-5 mt-0 text-sm text-sf-ink-mute">
        {backup ? 'Enter one of your backup codes.' : 'Enter the 6-digit code from your authenticator app.'}
      </p>
      <label htmlFor="totp-code" className="sr-only">{backup ? 'Backup code' : 'Authentication code'}</label>
      <input id="totp-code" type="text" autoFocus value={code} onChange={e => setCode(e.target.value)}
        inputMode={backup ? 'text' : 'numeric'} autoComplete="one-time-code"
        placeholder={backup ? 'XXXX-XXXX' : '000000'} maxLength={backup ? 9 : 6}
        className={`${inputClass} text-center font-mono text-xl tracking-[0.2em]`} />
      <label className="mt-4 flex cursor-pointer items-center gap-2 text-sm text-sf-ink-mute">
        <input type="checkbox" checked={trust} onChange={e => setTrust(e.target.checked)} className="accent-sf-accent" />
        Trust this browser for 30 days
      </label>
      {error && <p role="alert" className="mb-0 mt-3 text-sm text-sf-red-text">{error}</p>}
      <button type="submit" disabled={busy || !code.trim()} className={`${buttonClass} mt-5`}>
        {busy ? 'Checking…' : 'Verify'}
      </button>
      <div className="mt-4 flex justify-between">
        <button type="button" className="cursor-pointer border-0 bg-transparent p-0 text-sm text-sf-ink-mute"
          onClick={() => onRestart('')}>
          ← Back
        </button>
        <button type="button" className={btnLink} onClick={() => { setBackup(b => !b); setCode(''); setError(''); }}>
          {backup ? 'Use an authenticator code' : 'Use a backup code'}
        </button>
      </div>
    </form>
  );
}
