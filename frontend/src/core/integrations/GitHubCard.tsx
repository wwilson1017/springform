import { useState, type FormEvent } from 'react';
import { del, putJson } from '../api/client';
import { useJson } from '../api/useJson';
import BootFallback from '../components/BootFallback';
import { SETTINGS_URL, type CoreSettings } from '../settings/types';
import { buttonClass, chipClass, errorText, errorTextClass, inputClass, labelClass, secondaryButtonClass } from '../settings/ui';
import { confirmDialog } from '../../shared/confirm';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';

/** Where Requests become issues: the repository, its token (write-only) and the warning shown on the form. */
export default function GitHubCard() {
  const { data, error, reload, setData } = useJson<CoreSettings>(SETTINGS_URL);
  if (error) return <LoadError label="Couldn't load settings" onRetry={reload} compact />;
  if (!data) return <BootFallback variant="panel" />;
  return (
    <div className="flex flex-col gap-6">
      <RepoForm settings={data} onSaved={setData} />
      <TokenForm settings={data} onSaved={setData} />
    </div>
  );
}

interface FormProps {
  settings: CoreSettings;
  onSaved: (s: CoreSettings) => void;
}

function RepoForm({ settings, onSaved }: FormProps) {
  const [repo, setRepo] = useState(String(settings.values['github.repo'] ?? ''));
  const [warning, setWarning] = useState(String(settings.values['requests.warning_text'] ?? ''));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changed = repo !== settings.values['github.repo'] || warning !== settings.values['requests.warning_text'];

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const next = await putJson<CoreSettings>(SETTINGS_URL, { values: { 'github.repo': repo, 'requests.warning_text': warning } });
      setRepo(String(next.values['github.repo']));
      setWarning(String(next.values['requests.warning_text']));
      onSaved(next);
      toast.success('GitHub settings saved');
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="flex flex-col gap-3">
      <div>
        <label htmlFor="gh-repo" className={labelClass}>Repository</label>
        <input id="gh-repo" value={repo} onChange={e => setRepo(e.target.value)} placeholder="owner/name" className={`${inputClass} max-w-sm`} />
        <p className="mb-0 mt-1 text-xs text-sf-ink-dim">Requests become issues here, labelled with the app they are about.</p>
      </div>
      <div>
        <label htmlFor="gh-warning" className={labelClass}>Warning on the request form</label>
        <textarea id="gh-warning" value={warning} onChange={e => setWarning(e.target.value)} rows={3} maxLength={2000} className={inputClass} />
      </div>
      {error && <p role="alert" className={errorTextClass}>{error}</p>}
      <div><button type="submit" disabled={busy || !changed} className={buttonClass}>{busy ? 'Saving…' : 'Save'}</button></div>
    </form>
  );
}

function TokenForm({ settings, onSaved }: FormProps) {
  const isSet = Boolean(settings.secrets['github.token']);
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(request: () => Promise<CoreSettings>, done: string) {
    setBusy(true);
    setError(null);
    try {
      onSaved(await request());
      setToken('');
      toast.success(done);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function clear() {
    const ok = await confirmDialog({
      title: 'Clear the GitHub token', danger: true, confirmLabel: 'Clear token',
      message: 'New requests will not reach GitHub until a token is set again.',
    });
    // DELETE answers with the same settings view as PUT.
    if (ok) void run(() => del(`${SETTINGS_URL}/github.token`) as unknown as Promise<CoreSettings>, 'Token cleared');
  }

  return (
    <form className="flex flex-col gap-3"
      onSubmit={e => { e.preventDefault(); void run(() => putJson<CoreSettings>(SETTINGS_URL, { values: { 'github.token': token } }), 'Token saved'); }}>
      <div>
        <span className="mb-1 flex items-center gap-2">
          <label htmlFor="gh-token" className={`${labelClass} mb-0`}>Token</label>
          <span className={chipClass}>{isSet ? 'Set' : 'Not set'}</span>
        </span>
        <input id="gh-token" type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)}
          placeholder={isSet ? 'Paste a new token to replace it' : 'github_pat_…'} className={`${inputClass} max-w-sm`} />
        <p className="mb-0 mt-1 text-xs text-sf-ink-dim">
          A fine-grained token for this repository with Issues read and write. It is stored encrypted and never shown again.
        </p>
      </div>
      {error && <p role="alert" className={errorTextClass}>{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={busy || !token.trim()} className={buttonClass}>Save token</button>
        {isSet && <button type="button" disabled={busy} onClick={() => void clear()} className={secondaryButtonClass}>Clear</button>}
      </div>
    </form>
  );
}
