/**
 * Google sign-in for the install: the OAuth client id and secret (stored encrypted), the redirect
 * URI to register with Google (built from PUBLIC_URL, read-only), and whether a Google sign-in
 * also asks for the local 2FA code. "Test" checks what can be checked without Google.
 */

import { useState, type FormEvent } from 'react';
import { postJson, putJson } from '../api/client';
import { useJson } from '../api/useJson';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import {
  alertText, btnLink, btnPrimary, btnSecondary, errorText, inputSm, labelSm, noteText,
  type GoogleConfig, type GoogleTest,
} from './api';
import { CopyField } from './fields';

const putConfig = (body: Partial<GoogleConfig> & { client_secret?: string }) => putJson<GoogleConfig>('/api/auth/google/config', body);

export default function GoogleConfigCard() {
  const { data: config, error, reload, setData } = useJson<GoogleConfig>('/api/auth/google/config');
  if (error) return <LoadError label="Couldn't load the Google settings" onRetry={reload} compact />;
  if (!config) return <p className={noteText}>Loading…</p>;
  return <ConfigForm config={config} onSaved={setData} />;
}

function ConfigForm({ config, onSaved }: { config: GoogleConfig; onSaved: (c: GoogleConfig) => void }) {
  const [clientId, setClientId] = useState(config.client_id);
  const [secret, setSecret] = useState('');
  const [problem, setProblem] = useState('');
  const [busy, setBusy] = useState(false);
  const [test, setTest] = useState<GoogleTest | null>(null);

  async function save(body: Parameters<typeof putConfig>[0], done: string) {
    setProblem('');
    setTest(null);
    setBusy(true);
    try {
      const saved = await putConfig(body);
      onSaved(saved);
      setClientId(saved.client_id);
      setSecret('');
      toast.success(done);
    } catch (err) {
      setProblem(errorText(err, {}, "Couldn't save the Google settings."));
    } finally {
      setBusy(false);
    }
  }

  async function runTest() {
    setProblem('');
    setBusy(true);
    try {
      setTest(await postJson<GoogleTest>('/api/auth/google/test'));
    } catch (err) {
      setProblem(errorText(err, {}, "Couldn't run the test."));
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void save({ client_id: clientId.trim(), ...(secret ? { client_secret: secret } : {}) }, 'Google settings saved.');
  }

  return (
    <div className="flex max-w-xl flex-col gap-5">
      <p className={noteText}>
        Create an OAuth client (type "Web application") in Google Cloud, add the redirect URI below
        to it, then paste its client ID and secret here.
      </p>
      <div>
        <p className={labelSm}>Redirect URI</p>
        <CopyField label="Redirect URI" value={config.redirect_uri} mono />
      </div>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <div>
          <label htmlFor="google-client-id" className={labelSm}>Client ID</label>
          <input id="google-client-id" value={clientId} onChange={e => setClientId(e.target.value)} autoComplete="off"
            placeholder="1234567890-abc123.apps.googleusercontent.com" className={`${inputSm} font-mono text-xs`} />
        </div>
        <div>
          <label htmlFor="google-secret" className={labelSm}>Client secret</label>
          <input id="google-secret" type="password" value={secret} onChange={e => setSecret(e.target.value)} autoComplete="off"
            placeholder={config.has_secret ? 'Saved. Type a new one to replace it.' : 'Not set'} className={inputSm} />
          {config.has_secret && (
            <button type="button" disabled={busy} className={`${btnLink} mt-1 text-xs`}
              onClick={() => void save({ client_secret: '' }, 'Client secret cleared.')}>
              Clear the saved secret
            </button>
          )}
        </div>
        {problem && <p role="alert" className={alertText}>{problem}</p>}
        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={busy || (clientId.trim() === config.client_id && !secret)} className={btnPrimary}>Save</button>
          <button type="button" disabled={busy} className={btnSecondary} onClick={() => void runTest()}>Test</button>
        </div>
      </form>
      {test && (
        <div role="status" className={`rounded-md border p-3 text-sm ${test.ok ? 'border-sf-green' : 'border-sf-red'}`}>
          {test.ok
            ? <p className="m-0 text-sf-ink"><span className="font-medium text-sf-green-text">Looks right.</span> Sign in with Google from a private window to finish checking.</p>
            : (
              <>
                <p className="m-0 mb-1 font-medium text-sf-red-text">Not ready yet:</p>
                <ul className="m-0 pl-5 text-sf-ink">{test.problems.map(p => <li key={p}>{p}</li>)}</ul>
              </>
            )}
        </div>
      )}
      <div>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-sf-ink">
          <input type="checkbox" checked={config.require_totp_for_google} disabled={busy} aria-describedby="google-totp-hint"
            className="accent-sf-accent"
            onChange={e => void save({ require_totp_for_google: e.target.checked }, e.target.checked
              ? 'Google sign-ins now ask for the 2FA code too.' : 'Google sign-ins no longer ask for the 2FA code.')} />
          Ask for the two-factor code after Google too
        </label>
        <p id="google-totp-hint" className="m-0 mt-1 pl-6 text-xs text-sf-ink-dim">
          Off by default: Springform does not check whether the Google account itself uses 2-step verification.
          Applies to people who turned on two-factor here.
        </p>
      </div>
    </div>
  );
}
