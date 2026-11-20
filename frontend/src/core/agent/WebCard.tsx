import { useState } from 'react';
import { putJson } from '../api/client';
import { useJson } from '../api/useJson';
import BootFallback from '../components/BootFallback';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import type { CoreSettings } from '../settings/types';
import { HINT, INPUT, LABEL } from './ui';

const ENABLED = 'web.enabled';
const PROVIDER = 'web.search_provider';
const MAX_USES = 'web.search_max_uses';
const USES = Array.from({ length: 20 }, (_, i) => i + 1);

/** Settings, AI: Whisk's web search and page reading (`web.*`). */
export default function WebCard() {
  const { data, error, reload, setData } = useJson<CoreSettings>('/api/core/settings');
  const [busy, setBusy] = useState(false);
  if (error) return <LoadError label="Couldn't load the settings" onRetry={reload} />;
  if (!data) return <BootFallback variant="panel" />;
  const on = data.values[ENABLED] === true;
  const provider = data.values[PROVIDER] === 'anthropic' ? 'anthropic' : 'free';

  async function save(key: string, value: unknown, done: string) {
    setBusy(true);
    try {
      setData(await putJson<CoreSettings>('/api/core/settings', { values: { [key]: value } }));
      toast.success(done);
    } catch {
      toast.error("Couldn't save the setting.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <label className="flex cursor-pointer items-center gap-2 text-sm text-sf-ink">
        <input
          type="checkbox"
          checked={on}
          disabled={busy}
          onChange={(e) => void save(ENABLED, e.target.checked, e.target.checked ? 'Web tools on.' : 'Web tools off.')}
        />
        Let Whisk search the web and read web pages
      </label>
      <p className={HINT}>
        What Whisk reads on the web is treated as untrusted: after it reads a page or a search result, every change it
        wants to make in that conversation asks for your approval first. Pages on your own network are never read.
      </p>
      {on && (
        <div className="flex flex-wrap gap-3">
          <label className={LABEL}>
            Search with
            <select
              className={INPUT}
              value={provider}
              disabled={busy}
              onChange={(e) => void save(PROVIDER, e.target.value, 'Search provider saved.')}
            >
              <option value="free">DuckDuckGo (free, no key)</option>
              <option value="anthropic">Claude&apos;s own web search (Anthropic key, billed per search)</option>
            </select>
          </label>
          {provider === 'anthropic' && (
            <label className={LABEL}>
              Searches per reply
              <select
                className={INPUT}
                value={Number(data.values[MAX_USES] ?? 5)}
                disabled={busy}
                onChange={(e) => void save(MAX_USES, Number(e.target.value), 'Searches per reply saved.')}
              >
                {USES.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      )}
      {on && provider === 'anthropic' && (
        <p className={HINT}>
          Claude&apos;s search is used while Whisk runs on Anthropic; on OpenAI it uses DuckDuckGo.
        </p>
      )}
    </div>
  );
}
