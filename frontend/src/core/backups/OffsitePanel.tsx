import { useState, type ChangeEvent, type FormEvent, type InputHTMLAttributes } from 'react';
import { Link } from 'react-router';
import { ApiError, del, postJson, putJson } from '../api/client';
import { buttonClass, chipClass, errorTextClass, inputClass, labelClass, secondaryButtonClass } from '../settings/ui';
import { confirmDialog } from '../../shared/confirm';
import { formatDate } from '../../shared/formatDate';
import { toast } from '../../shared/toast';
import { formatBytes } from './format';
import type { DestinationBody, Offsite } from './types';

const URL = '/api/core/backups';

/** The server's detail at any status: a 502 carries the storage service's own refusal. */
const detail = (e: unknown) => (e instanceof ApiError ? e.detail : "Couldn't reach the server. Try again.");

/** The off-site copy (shape and copy from CakeCRM's BackupsCard): status, destination, passphrase. */
export function OffsitePanel({ offsite, onChanged }: { offsite: Offsite; onChanged: () => void }) {
  return (
    <div className="flex flex-col gap-5">
      <p className="m-0 text-sm text-sf-ink-mute">
        After each backup, the set (the database and its attached files) is uploaded to a bucket you own on any
        S3-compatible storage, and sets past the number you keep are removed there. A backup does not hold the
        encryption key or the server's <code>.env</code>: keep the key somewhere other than this bucket.
      </p>
      <Status offsite={offsite} />
      <DestinationForm offsite={offsite} onChanged={onChanged} />
      <PassphraseForm offsite={offsite} onChanged={onChanged} />
    </div>
  );
}

function Status({ offsite }: { offsite: Offsite }) {
  if (!offsite.configured)
    return <p className="m-0 text-sm text-sf-ink-mute">No destination yet: backups stay on this server.</p>;
  return (
    <div className="flex flex-col gap-1 text-sm">
      <p className="m-0 text-sf-ink">
        Last good upload:{' '}
        {offsite.last_success_at
          ? `${formatDate(offsite.last_success_at)} · ${formatBytes(offsite.last_success_bytes)}`
          : 'none yet'}
      </p>
      {offsite.stale && <p className="m-0 text-sf-amber-text">No good off-site upload in more than two days.</p>}
      {offsite.last_error && <p className="m-0 break-words text-sf-red-text">Last error: {offsite.last_error}</p>}
    </div>
  );
}

function useAction(onChanged: () => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run(request: () => Promise<unknown>, done: string): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      await request();
      toast.success(done);
      onChanged();
      return true;
    } catch (e) {
      setError(detail(e));
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, run };
}

function Field({
  id,
  label,
  hint,
  ...input
}: { id: string; label: string; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div>
      <label htmlFor={id} className={labelClass}>
        {label}
      </label>
      <input id={id} className={`${inputClass} max-w-md`} autoComplete="off" {...input} />
      {hint && <p className="mb-0 mt-1 text-xs text-sf-ink-dim">{hint}</p>}
    </div>
  );
}

/** The form's fields for a destination as the server holds it (canonical: `shop` is saved as `shop/`). */
const formFrom = (offsite: Offsite) => ({
  endpoint: offsite.endpoint ?? '',
  bucket: offsite.bucket ?? '',
  region: offsite.region ?? 'us-east-1',
  prefix: offsite.prefix ?? '',
  access_key_id: offsite.access_key_id ?? '',
  secret_key: '',
  retention: String(offsite.retention ?? 30),
});

function DestinationForm({ offsite, onChanged }: { offsite: Offsite; onChanged: () => void }) {
  const [form, setForm] = useState(() => formFrom(offsite));
  const { busy, error, run } = useAction(onChanged);
  const set = (k: keyof typeof form) => (e: ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  function save(e: FormEvent) {
    e.preventDefault();
    const body: DestinationBody = { ...form, retention: Number(form.retention), secret_key: form.secret_key || null };
    void run(async () => setForm(formFrom(await putJson<Offsite>(`${URL}/destination`, body))), 'Destination saved');
  }

  async function remove() {
    const ok = await confirmDialog({
      title: 'Remove the destination',
      danger: true,
      confirmLabel: 'Remove',
      message: 'Backups stop going off-site. What is already in the bucket stays there.',
    });
    if (ok) void run(() => del(`${URL}/destination`), 'Destination removed');
  }

  const saved = offsite.configured && !offsite.unreadable;
  // Test connection checks the SAVED destination, so it waits until edits are saved.
  const edited =
    form.secret_key !== '' ||
    (['endpoint', 'bucket', 'region', 'prefix', 'access_key_id'] as const).some(
      (k) => form[k] !== (offsite[k] ?? ''),
    ) ||
    form.retention !== String(offsite.retention ?? 30);
  return (
    <form onSubmit={save} className="flex flex-col gap-3">
      <h3 className="m-0 text-sm font-medium text-sf-ink">Destination</h3>
      <p className="m-0 text-sm text-sf-ink-mute">
        Recommended:{' '}
        <Link to="/guide/backups-cloudflare-r2" className="text-sf-accent-text">
          Cloudflare R2 (free for small installs)
        </Link>
        , with step-by-step setup.
      </p>
      <Field
        id="os-endpoint"
        label="Endpoint"
        value={form.endpoint}
        onChange={set('endpoint')}
        required
        placeholder="https://<account>.r2.cloudflarestorage.com"
      />
      <Field id="os-bucket" label="Bucket" value={form.bucket} onChange={set('bucket')} required />
      <Field
        id="os-region"
        label="Region"
        value={form.region}
        onChange={set('region')}
        required
        hint="us-east-1 unless your provider says otherwise; Cloudflare R2 uses auto."
      />
      <Field
        id="os-prefix"
        label="Path prefix (optional)"
        value={form.prefix}
        onChange={set('prefix')}
        hint="A folder only this install writes to."
      />
      <Field id="os-key-id" label="Access key id" value={form.access_key_id} onChange={set('access_key_id')} required />
      <Field
        id="os-secret"
        label="Secret access key"
        type="password"
        value={form.secret_key}
        onChange={set('secret_key')}
        required={!saved}
        placeholder={saved ? 'Saved; leave blank to keep it' : ''}
      />
      <Field
        id="os-retention"
        label="Sets to keep"
        type="number"
        min={1}
        max={365}
        value={form.retention}
        onChange={set('retention')}
        required
      />
      {error && (
        <p role="alert" className={errorTextClass}>
          {error}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={busy} className={buttonClass}>
          Save destination
        </button>
        {saved && (
          <button
            type="button"
            disabled={busy || edited}
            title={edited ? 'Save the destination first: the test uses the saved one.' : undefined}
            className={secondaryButtonClass}
            onClick={() => void run(() => postJson(`${URL}/destination/test`), 'Connection works')}
          >
            Test connection
          </button>
        )}
        {offsite.configured && (
          <button type="button" disabled={busy} onClick={() => void remove()} className={secondaryButtonClass}>
            Remove destination
          </button>
        )}
      </div>
    </form>
  );
}

function PassphraseForm({ offsite, onChanged }: { offsite: Offsite; onChanged: () => void }) {
  const [passphrase, setPassphrase] = useState('');
  const { busy, error, run } = useAction(onChanged);

  async function remove() {
    const ok = await confirmDialog({
      title: 'Remove the backup passphrase',
      danger: true,
      confirmLabel: 'Remove',
      message: 'New uploads and downloads will not be encrypted. Sets already uploaded still need the old passphrase.',
    });
    if (ok) void run(() => del(`${URL}/passphrase`), 'Passphrase removed');
  }

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        void run(() => putJson(`${URL}/passphrase`, { passphrase }), 'Passphrase set').then(
          (ok) => ok && setPassphrase(''),
        );
      }}
    >
      <span className="flex items-center gap-2">
        <h3 className="m-0 text-sm font-medium text-sf-ink">Backup passphrase (optional)</h3>
        <span className={chipClass}>{offsite.encrypted ? 'Set' : 'Not set'}</span>
      </span>
      <p className="m-0 text-sm text-sf-ink-mute">
        With a passphrase, every uploaded file and every download is encrypted with{' '}
        <a href="https://age-encryption.org" target="_blank" rel="noreferrer" className="text-sf-accent-text">
          age
        </a>{' '}
        and ends in <code>.age</code>; <code>age -d</code> and the passphrase open it, no app needed. Without one,
        downloads are plain <code>.sqlite</code> files.{' '}
        <strong className="text-sf-ink">
          If you lose this passphrase, the encrypted backups cannot be opened. Springform cannot recover it.
        </strong>
      </p>
      <Field
        id="os-passphrase"
        label={offsite.encrypted ? 'New passphrase' : 'Passphrase'}
        type="password"
        value={passphrase}
        onChange={(e) => setPassphrase(e.target.value)}
        minLength={8}
        required
        hint="At least 8 characters. Keep it in your password manager."
      />
      {error && (
        <p role="alert" className={errorTextClass}>
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <button type="submit" disabled={busy || passphrase.length < 8} className={buttonClass}>
          {offsite.encrypted ? 'Change passphrase' : 'Set passphrase'}
        </button>
        {offsite.encrypted && (
          <button type="button" disabled={busy} onClick={() => void remove()} className={secondaryButtonClass}>
            Remove passphrase
          </button>
        )}
      </div>
    </form>
  );
}
