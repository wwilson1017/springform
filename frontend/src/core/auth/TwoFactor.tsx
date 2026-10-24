/**
 * Authenticator-app 2FA for the signed-in user: enrol (QR + the secret as text), confirm with a
 * code, then the ten backup codes, shown once, to copy or download. Turning it off takes a code
 * or a backup code. Turning it on or off forgets trusted browsers (`onChange`).
 */

import QRCode from 'qrcode';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { postJson } from '../api/client';
import { useJson } from '../api/useJson';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { alertText, btnDanger, btnLink, btnPrimary, btnSecondary, errorText, inputSm, labelSm, noteText, type TotpStatus } from './api';
import { CopyField } from './fields';

type Step = { kind: 'status' } | { kind: 'enrol'; secret: string; uri: string } | { kind: 'codes'; codes: string[] } | { kind: 'disable' };

const CODE_ERRORS = {
  invalid_code: "That code didn't work. Enter the newest one from your app.",
  totp_already_enabled: 'Two-factor authentication is already on.',
  totp_not_pending: 'That setup expired. Start again.',
  totp_not_enabled: 'Two-factor authentication is already off.',
};

export function TwoFactor({ onChange }: { onChange: () => void }) {
  const { data: status, error, reload } = useJson<TotpStatus>('/api/auth/totp');
  const [step, setStep] = useState<Step>({ kind: 'status' });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');

  async function run<T>(fn: () => Promise<T>, fallback: string): Promise<T | undefined> {
    setProblem('');
    setBusy(true);
    try {
      return await fn();
    } catch (err) {
      setProblem(errorText(err, CODE_ERRORS, fallback));
    } finally {
      setBusy(false);
    }
  }

  async function start() {
    const r = await run(() => postJson<{ secret: string; otpauth_uri: string }>('/api/auth/totp/enrol'), "Couldn't start setup.");
    if (r) setStep({ kind: 'enrol', secret: r.secret, uri: r.otpauth_uri });
  }

  if (error) return <LoadError label="Couldn't load your two-factor status" onRetry={reload} compact />;
  if (!status) return <p className={noteText}>Loading…</p>;

  if (step.kind === 'enrol') {
    return (
      <div className="flex flex-col gap-4">
        <p className={noteText}>Scan this with an authenticator app (Google Authenticator, 1Password, Authy…), then enter the 6-digit code it shows.</p>
        <QrCanvas text={step.uri} />
        <div>
          <p className={labelSm}>Or type this key into the app</p>
          <CopyField label="Setup key" value={step.secret} mono />
        </div>
        <CodeForm label="Code from the app" submit="Turn on" busy={busy} problem={problem}
          onCancel={() => { setProblem(''); setStep({ kind: 'status' }); }}
          onSubmit={async code => {
            const r = await run(() => postJson<{ backup_codes: string[] }>('/api/auth/totp/confirm', { code }), "Couldn't turn on two-factor authentication.");
            if (r) { setStep({ kind: 'codes', codes: r.backup_codes }); onChange(); }
          }} />
      </div>
    );
  }

  if (step.kind === 'codes') {
    return <BackupCodes codes={step.codes} onDone={() => { reload(); setStep({ kind: 'status' }); }} />;
  }

  if (step.kind === 'disable') {
    return (
      <div className="flex flex-col gap-3">
        <p className={noteText}>To turn it off, confirm with a code from your app or a backup code.</p>
        <CodeForm label="Code" submit="Turn off" danger allowBackup busy={busy} problem={problem}
          onCancel={() => { setProblem(''); setStep({ kind: 'status' }); }}
          onSubmit={async (code, backup) => {
            const r = await run(() => postJson('/api/auth/totp/disable', backup ? { backup_code: code } : { code }), "Couldn't turn off two-factor authentication.");
            if (r) { toast.success('Two-factor authentication is off.'); reload(); setStep({ kind: 'status' }); onChange(); }
          }} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {status.enabled ? (
        <>
          <p className="m-0 text-sm text-sf-ink"><span className="font-medium text-sf-green-text">On.</span> Signing in asks for a code from your authenticator app.</p>
          <p className={status.backup_codes_left <= 2 ? alertText : noteText}>
            {status.backup_codes_left} backup {status.backup_codes_left === 1 ? 'code' : 'codes'} left.
            {status.backup_codes_left <= 2 && ' Turn two-factor off and on again for a fresh set.'}
          </p>
          <div><button type="button" className={btnSecondary} onClick={() => { setProblem(''); setStep({ kind: 'disable' }); }}>Turn off</button></div>
        </>
      ) : (
        <>
          <p className={noteText}>Off. Add a second step to signing in: a 6-digit code from an authenticator app on your phone.</p>
          {problem && <p role="alert" className={alertText}>{problem}</p>}
          <div><button type="button" className={btnPrimary} disabled={busy} onClick={() => void start()}>{busy ? 'Starting…' : 'Set up two-factor'}</button></div>
        </>
      )}
    </div>
  );
}

function QrCanvas({ text }: { text: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    // White quiet zone on every theme: scanners need dark modules on light.
    if (ref.current) QRCode.toCanvas(ref.current, text, { width: 192, margin: 2 }).catch(() => setFailed(true));
  }, [text]);
  if (failed) return <p className={noteText}>Couldn't draw the QR code; type the key below into your app instead.</p>;
  return <canvas ref={ref} role="img" aria-label="QR code for your authenticator app" className="self-start rounded-md" />;
}

function CodeForm({ label, submit, busy, problem, danger, allowBackup, onSubmit, onCancel }: {
  label: string; submit: string; busy: boolean; problem: string; danger?: boolean; allowBackup?: boolean;
  onSubmit: (code: string, backup: boolean) => Promise<void>; onCancel: () => void;
}) {
  const [code, setCode] = useState('');
  const [backup, setBackup] = useState(false);
  function go(e: FormEvent) {
    e.preventDefault();
    void onSubmit(code.trim(), backup).then(() => setCode(''));
  }
  return (
    <form onSubmit={go} className="flex max-w-xs flex-col gap-3">
      <div>
        <label htmlFor="totp-setting-code" className={labelSm}>{backup ? 'Backup code' : label}</label>
        <input id="totp-setting-code" value={code} onChange={e => setCode(e.target.value)} autoFocus autoComplete="one-time-code"
          inputMode={backup ? 'text' : 'numeric'} placeholder={backup ? 'XXXX-XXXX' : '000000'} maxLength={backup ? 9 : 6}
          className={`${inputSm} font-mono tracking-widest`} />
      </div>
      {allowBackup && (
        <button type="button" className={`${btnLink} self-start`} onClick={() => { setBackup(b => !b); setCode(''); }}>
          {backup ? 'Use an authenticator code' : 'Use a backup code'}
        </button>
      )}
      {problem && <p role="alert" className={alertText}>{problem}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={busy || !code.trim()}
          className={danger ? btnDanger : btnPrimary}>{busy ? 'Checking…' : submit}</button>
        <button type="button" className={btnSecondary} onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function BackupCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const text = `Springform backup codes for ${window.location.host}\nEach code works once.\n\n${codes.join('\n')}\n`;
  function download() {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'springform-backup-codes.txt';
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 text-sm text-sf-ink"><span className="font-medium text-sf-green-text">Two-factor authentication is on.</span></p>
      <p className={alertText}>
        Save these backup codes now; they won't be shown again. Each works once, if you lose your phone.
      </p>
      <ul aria-label="Backup codes" className="m-0 grid max-w-xs list-none grid-cols-2 gap-x-6 gap-y-2 rounded-md border border-sf-line-strong bg-sf-raised p-4 font-mono text-sm text-sf-ink">
        {codes.map(c => <li key={c}>{c}</li>)}
      </ul>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={btnSecondary}
          onClick={() => navigator.clipboard.writeText(codes.join('\n')).then(() => toast.success('Backup codes copied.'), () => toast.error("Couldn't copy; select the codes instead."))}>
          Copy all
        </button>
        <button type="button" className={btnSecondary} onClick={download}>Download .txt</button>
        <button type="button" className={btnPrimary} onClick={onDone}>I've saved them</button>
      </div>
    </div>
  );
}
