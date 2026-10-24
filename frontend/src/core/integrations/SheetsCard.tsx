import { useState, type FormEvent } from 'react';
import { putJson } from '../api/client';
import { useJson } from '../api/useJson';
import BootFallback from '../components/BootFallback';
import { buttonClass, errorText, errorTextClass, inputClass, labelClass, secondaryButtonClass } from '../settings/ui';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { SheetPreviewDrawer } from './SheetPreviewDrawer';
import { SheetRow } from './SheetRow';
import type { Sheet, SheetCredentials } from './types';

/** The Google service-account key, then every sheet the installed apps declare. */
export default function SheetsCard() {
  return (
    <div className="flex flex-col gap-6">
      <Credentials />
      <SheetList />
    </div>
  );
}

function Credentials() {
  const { data, error, reload, setData } = useJson<SheetCredentials>('/api/core/sheets/credentials');
  const [replacing, setReplacing] = useState(false);
  const [raw, setRaw] = useState('');
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  if (error) return <LoadError label="Couldn't load the Sheets key" onRetry={reload} compact />;
  if (!data) return <BootFallback variant="panel" />;

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setSaveError(null);
    try {
      setData(await putJson<SheetCredentials>('/api/core/sheets/credentials', { service_account_json: raw }));
      setRaw('');
      setReplacing(false);
      toast.success('Service-account key saved');
    } catch (err) {
      setSaveError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {data.configured && (
        <div>
          <div className={labelClass}>Service account</div>
          <div className="break-all font-mono text-sm text-sf-ink">{data.service_account_email}</div>
          <p className="mb-0 mt-1 text-sm text-sf-ink-mute">Share your sheet with this address: Viewer to read, Editor to write.</p>
        </div>
      )}
      {data.configured && !replacing ? (
        <div><button type="button" onClick={() => setReplacing(true)} className={secondaryButtonClass}>Replace key</button></div>
      ) : (
        <form onSubmit={save} className="flex flex-col gap-3">
          <div>
            <label htmlFor="sheets-key" className={labelClass}>Service-account key (JSON)</label>
            <textarea id="sheets-key" value={raw} onChange={e => setRaw(e.target.value)} rows={5} spellCheck={false}
              placeholder='{"type": "service_account", "client_email": "…", "private_key": "…"}'
              className={`${inputClass} font-mono text-xs`} />
            <p className="mb-0 mt-1 text-xs text-sf-ink-dim">
              Create a service account in Google Cloud, add a JSON key, and paste the whole file here. It is stored encrypted.
            </p>
          </div>
          {saveError && <p role="alert" className={errorTextClass}>{saveError}</p>}
          <div className="flex gap-2">
            <button type="submit" disabled={busy || !raw.trim()} className={buttonClass}>{busy ? 'Saving…' : 'Save key'}</button>
            {replacing && <button type="button" onClick={() => { setReplacing(false); setRaw(''); setSaveError(null); }} className={secondaryButtonClass}>Cancel</button>}
          </div>
        </form>
      )}
    </div>
  );
}

function SheetList() {
  const { data, error, reload, setData } = useJson<Sheet[]>('/api/core/sheets');
  const [previewing, setPreviewing] = useState<Sheet | null>(null);
  if (error) return <LoadError label="Couldn't load the connected sheets" onRetry={reload} compact />;
  if (!data) return <BootFallback variant="panel" />;
  const replace = (sheet: Sheet) => setData(data.map(s => (s.id === sheet.id ? sheet : s)));

  return (
    <div>
      <h3 className="m-0 mb-2 text-sm font-medium text-sf-ink">Connected sheets</h3>
      {data.length === 0 ? (
        <p className="m-0 text-sm text-sf-ink-mute">No installed app declares a sheet.</p>
      ) : (
        <ul className="m-0 list-none divide-y divide-sf-line p-0">
          {data.map(sheet => (
            <SheetRow key={sheet.id} sheet={sheet} onChange={replace} onReload={reload} onPreview={() => setPreviewing(sheet)} />
          ))}
        </ul>
      )}
      {previewing && <SheetPreviewDrawer sheet={previewing} onClose={() => setPreviewing(null)} />}
    </div>
  );
}
