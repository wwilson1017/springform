import { useState } from 'react';
import { putJson } from '../api/client';
import { useJson } from '../api/useJson';
import BootFallback from '../components/BootFallback';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import type { CoreSettings } from '../settings/types';
import { HINT } from './ui';

const KEY = 'agent.nightly_enabled';

/** Settings, AI: the nightly memory run (`core.agent_nightly`), off by default because it spends credits. */
export default function NightlyCard() {
  const { data, error, reload, setData } = useJson<CoreSettings>('/api/core/settings');
  const [busy, setBusy] = useState(false);
  if (error) return <LoadError label="Couldn't load the setting" onRetry={reload} />;
  if (!data) return <BootFallback variant="panel" />;
  const on = data.values[KEY] === true;

  async function toggle(next: boolean) {
    setBusy(true);
    try {
      setData(await putJson<CoreSettings>('/api/core/settings', { values: { [KEY]: next } }));
      toast.success(next ? 'Nightly run on.' : 'Nightly run off.');
    } catch {
      toast.error("Couldn't save the setting.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <label className="flex cursor-pointer items-center gap-2 text-sm text-sf-ink">
        <input type="checkbox" checked={on} disabled={busy} onChange={e => void toggle(e.target.checked)} />
        Run the nightly memory pass
      </label>
      <p className={HINT}>
        At 02:00 Whisk reads the day's conversations that are not private, saves the business facts it finds, and tidies
        its memory. It uses the light model, so it costs a little each night, and it is skipped while no AI key is set.
      </p>
    </div>
  );
}
