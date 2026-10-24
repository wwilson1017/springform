import { useState, type FormEvent } from 'react';
import { putJson } from '../api/client';
import { useJson } from '../api/useJson';
import BootFallback from '../components/BootFallback';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { SETTINGS_URL, type CoreSettings } from './types';
import { buttonClass, errorText, errorTextClass, inputClass, labelClass } from './ui';

const MB = 1024 * 1024;
const KEY = 'files.max_bytes';

/** The largest attachment anyone may upload (`files.max_bytes`), edited in MB. */
export default function FilesCard() {
  const { data, error, reload, setData } = useJson<CoreSettings>(SETTINGS_URL);
  if (error) return <LoadError label="Couldn't load settings" onRetry={reload} compact />;
  if (!data) return <BootFallback variant="panel" />;
  return <FilesForm settings={data} onSaved={setData} />;
}

function FilesForm({ settings, onSaved }: { settings: CoreSettings; onSaved: (s: CoreSettings) => void }) {
  const current = Number(settings.values[KEY]) / MB;
  const [mb, setMb] = useState(String(current));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSaved(await putJson<CoreSettings>(SETTINGS_URL, { values: { [KEY]: Math.round(Number(mb) * MB) } }));
      toast.success('Upload limit saved');
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="flex flex-col gap-3">
      <div>
        <label htmlFor="files-max" className={labelClass}>Largest upload (MB)</label>
        <input id="files-max" type="number" min="0.1" step="0.1" required value={mb} onChange={e => setMb(e.target.value)}
          className={`${inputClass} max-w-40`} />
        <p className="mb-0 mt-1 text-xs text-sf-ink-dim">Default {Number(settings.defaults[KEY]) / MB} MB. Applies to new uploads.</p>
      </div>
      {error && <p role="alert" className={errorTextClass}>{error}</p>}
      <div><button type="submit" disabled={busy || Number(mb) === current} className={buttonClass}>{busy ? 'Saving…' : 'Save'}</button></div>
    </form>
  );
}
