/**
 * The signed-in user's own security: password, two-factor, trusted browsers and the Google link.
 * Lazy (it carries the QR encoder). The Google link round-trip comes back to
 * /settings?google=linked or ?google_error=…, announced in settingsCards.ts.
 */

import { useState, type FormEvent, type ReactNode } from 'react';
import { del, postJson } from '../api/client';
import { useJson } from '../api/useJson';
import { confirmDialog } from '../../shared/confirm';
import { formatDate } from '../../shared/formatDate';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import {
  alertText, btnDanger, btnPrimary, btnSecondary, errorText, inputSm, labelSm, noteText,
  type GoogleStatus, type TrustedDevice,
} from './api';
import { TwoFactor } from './TwoFactor';

export default function SecurityCard() {
  const google = useJson<GoogleStatus>('/api/auth/google');
  const devices = useJson<TrustedDevice[]>('/api/auth/trusted-devices');
  return (
    <div className="flex flex-col divide-y divide-sf-line">
      <Part title="Password">
        {google.error ? <LoadError label="Couldn't load your sign-in methods" onRetry={google.reload} compact />
          : !google.data ? <p className={noteText}>Loading…</p>
          : google.data.has_password ? <PasswordForm onChanged={devices.reload} />
          : <p className={noteText}>{google.data.linked
            ? 'You sign in with Google, so there is no password to change.'
            : 'This account has no password.'}</p>}
      </Part>
      <Part title="Two-factor authentication">
        <TwoFactor onChange={devices.reload} />
      </Part>
      <Part title="Trusted browsers">
        <TrustedDevices list={devices.data} error={devices.error} reload={devices.reload} />
      </Part>
      <Part title="Google">
        {google.data && <GoogleLink status={google.data} onChange={google.setData} />}
      </Part>
    </div>
  );
}

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="py-5 first:pt-0 last:pb-0">
      <h3 className="m-0 mb-3 text-sm font-medium text-sf-ink">{title}</h3>
      {children}
    </section>
  );
}

function PasswordForm({ onChanged }: { onChanged: () => void }) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const mismatch = confirm.length > 0 && next !== confirm;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      // The answer carries a fresh session cookie: the change ends every other session.
      await postJson('/api/auth/password', { current, new: next });
      setCurrent(''); setNext(''); setConfirm('');
      toast.success('Password changed. Other sessions are signed out.');
      onChanged();
    } catch (err) {
      setError(errorText(err, { wrong_password: 'Your current password is wrong.' }, "Couldn't change your password."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex max-w-xs flex-col gap-3">
      <div>
        <label htmlFor="pw-current" className={labelSm}>Current password</label>
        <input id="pw-current" type="password" autoComplete="current-password" value={current} onChange={e => setCurrent(e.target.value)} className={inputSm} />
      </div>
      <div>
        <label htmlFor="pw-new" className={labelSm}>New password</label>
        <input id="pw-new" type="password" autoComplete="new-password" value={next} onChange={e => setNext(e.target.value)} placeholder="At least 8 characters" className={inputSm} />
      </div>
      <div>
        <label htmlFor="pw-confirm" className={labelSm}>Confirm new password</label>
        <input id="pw-confirm" type="password" autoComplete="new-password" value={confirm} aria-invalid={mismatch} onChange={e => setConfirm(e.target.value)} className={inputSm} />
        {mismatch && <p className="mb-0 mt-1 text-xs text-sf-red-text">Passwords don't match.</p>}
      </div>
      {error && <p role="alert" className={alertText}>{error}</p>}
      <div>
        <button type="submit" disabled={busy || !current || next.length < 8 || next !== confirm} className={btnPrimary}>
          {busy ? 'Changing…' : 'Change password'}
        </button>
      </div>
    </form>
  );
}

/** "Chrome on macOS" from the user agent the server stored (the full string stays in the tooltip). */
function browserName(ua: string): string {
  const browser = /Edg\//.test(ua) ? 'Edge' : /Firefox\//.test(ua) ? 'Firefox' : /Chrome\//.test(ua) ? 'Chrome' : /Safari\//.test(ua) ? 'Safari' : '';
  const os = /iPhone|iPad/.test(ua) ? 'iOS' : /Android/.test(ua) ? 'Android' : /Mac OS X/.test(ua) ? 'macOS'
    : /Windows/.test(ua) ? 'Windows' : /Linux/.test(ua) ? 'Linux' : '';
  return browser && os ? `${browser} on ${os}` : browser || os || ua || 'Unknown browser';
}

function TrustedDevices({ list, error, reload }: { list: TrustedDevice[] | null; error: Error | null; reload: () => void }) {
  const [busy, setBusy] = useState(false);
  if (error) return <LoadError label="Couldn't load trusted browsers" onRetry={reload} compact />;
  if (!list) return <p className={noteText}>Loading…</p>;

  async function forgetAll() {
    if (!await confirmDialog({ title: 'Forget all browsers', message: 'Every browser, this one included, will ask for a two-factor code at the next sign-in.', confirmLabel: 'Forget all', danger: true })) return;
    setBusy(true);
    try {
      await del('/api/auth/trusted-devices');
      toast.success('Trusted browsers forgotten.');
      reload();
    } catch {
      toast.error("Couldn't forget the browsers.");
    } finally {
      setBusy(false);
    }
  }

  if (list.length === 0) {
    return <p className={noteText}>None. Tick "Trust this browser" at the two-factor step to skip it on that browser for 30 days.</p>;
  }
  return (
    <div className="flex flex-col gap-3">
      <ul className="m-0 list-none divide-y divide-sf-line p-0">
        {list.map(d => (
          <li key={d.created_at + d.label} className="py-2 text-sm">
            <div className="truncate text-sf-ink" title={d.label}>{browserName(d.label)}{d.current && <span className="text-sf-green-text"> · this browser</span>}</div>
            <div className="text-xs text-sf-ink-dim">Trusted {formatDate(d.created_at)} · until {formatDate(d.expires_at)}</div>
          </li>
        ))}
      </ul>
      <div><button type="button" disabled={busy} className={btnDanger} onClick={() => void forgetAll()}>Forget all</button></div>
    </div>
  );
}

function GoogleLink({ status, onChange }: { status: GoogleStatus; onChange: (s: GoogleStatus) => void }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function unlink() {
    if (!await confirmDialog({ title: 'Unlink Google', message: 'You will sign in with your password only.', confirmLabel: 'Unlink' })) return;
    setError('');
    setBusy(true);
    try {
      await postJson('/api/auth/google/unlink');
      onChange({ ...status, linked: false });
      toast.success('Google unlinked.');
    } catch (err) {
      setError(errorText(err, {
        password_required: "You have no password yet, so unlinking Google would leave you no way to sign in.",
      }, "Couldn't unlink Google."));
    } finally {
      setBusy(false);
    }
  }

  if (status.linked) {
    return (
      <div className="flex flex-col gap-3">
        <p className="m-0 text-sm text-sf-ink"><span className="font-medium text-sf-green-text">Linked.</span> You can sign in with "Continue with Google".</p>
        {error && <p role="alert" className={alertText}>{error}</p>}
        <div><button type="button" disabled={busy} className={btnSecondary} onClick={() => void unlink()}>Unlink Google</button></div>
      </div>
    );
  }
  if (!status.available) return <p className={noteText}>Google sign-in isn't set up on this install. An admin can turn it on under Settings → Sign-in.</p>;
  return (
    <div className="flex flex-col gap-3">
      <p className={noteText}>Link a Google account to sign in with "Continue with Google". You'll pick the account on Google's page.</p>
      {/* A top-level navigation: the server redirects to Google and back to /settings. */}
      <div><a href="/api/auth/google/start?link=1" className={`${btnSecondary} inline-block no-underline`}>Link Google</a></div>
    </div>
  );
}
