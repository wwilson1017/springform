import { useState, type FormEvent } from 'react';
import { putJson } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import BootFallback from '../components/BootFallback';
import { toast } from '../../shared/toast';
import { SETTINGS_URL, type CoreSettings, type Workspace } from './types';
import { buttonClass, chipClass, errorText, errorTextClass, inputClass, labelClass } from './ui';
import { setWorkspace, useWorkspace } from './useWorkspace';

const TIMEZONES = Intl.supportedValuesOf('timeZone');

/** Install name and timezone (admins edit them), with the running version and the preview flag. */
export function WorkspaceCard() {
  const { isAdmin } = useAuth();
  const workspace = useWorkspace();
  if (!workspace) return <BootFallback variant="panel" />;
  return (
    <div className="flex flex-col gap-4">
      {isAdmin ? <WorkspaceForm workspace={workspace} /> : (
        <dl className="m-0 grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-sf-ink-dim">Name</dt><dd className="m-0 text-sf-ink">{workspace.name}</dd>
          <dt className="text-sf-ink-dim">Timezone</dt><dd className="m-0 text-sf-ink">{workspace.timezone}</dd>
        </dl>
      )}
      <p className="m-0 flex items-center gap-2 text-xs text-sf-ink-dim">
        Springform {workspace.version}
        {workspace.preview && <span className={chipClass}>Preview mode</span>}
      </p>
    </div>
  );
}

function WorkspaceForm({ workspace }: { workspace: Workspace }) {
  const [name, setName] = useState(workspace.name);
  const [timezone, setTimezone] = useState(workspace.timezone);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changed = name !== workspace.name || timezone !== workspace.timezone;

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { values } = await putJson<CoreSettings>(SETTINGS_URL, { values: { 'workspace.name': name, timezone } });
      const saved = { ...workspace, name: String(values['workspace.name']), timezone: String(values.timezone) };
      setName(saved.name);
      setTimezone(saved.timezone);
      setWorkspace(saved);
      toast.success('Workspace saved');
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="flex max-w-md flex-col gap-3">
      <div>
        <label htmlFor="ws-name" className={labelClass}>Name</label>
        <input id="ws-name" value={name} onChange={e => setName(e.target.value)} maxLength={80} required className={inputClass} />
      </div>
      <div>
        <label htmlFor="ws-tz" className={labelClass}>Timezone</label>
        <input id="ws-tz" value={timezone} onChange={e => setTimezone(e.target.value)} list="ws-tz-list" required
          placeholder="America/Chicago" className={inputClass} />
        <datalist id="ws-tz-list">{TIMEZONES.map(tz => <option key={tz} value={tz} />)}</datalist>
        <p className="mb-0 mt-1 text-xs text-sf-ink-dim">Scheduled jobs, reminders and the days in reports follow this timezone.</p>
      </div>
      {error && <p role="alert" className={errorTextClass}>{error}</p>}
      <div><button type="submit" disabled={busy || !changed} className={buttonClass}>{busy ? 'Saving…' : 'Save'}</button></div>
    </form>
  );
}
