import { useState } from 'react';
import { ApiError, postJson, putJson } from '../api/client';
import { useJson } from '../api/useJson';
import BootFallback from '../components/BootFallback';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import type { ProviderInfo, ProviderTest } from './types';
import { BUTTON, HINT, INPUT, LABEL, PRIMARY } from './ui';

const NAMES: Record<string, string> = { anthropic: 'Anthropic (Claude)', openai: 'OpenAI (GPT)' };

type Patch = { api_key?: string; model_default?: string; model_light?: string; enabled?: boolean };

/** One provider: its key (set, replace, remove), its two model tiers, on/off, and a test call. */
function ProviderRow({ p, onSaved }: { p: ProviderInfo; onSaved: (p: ProviderInfo) => void }) {
  const [key, setKey] = useState('');
  const [models, setModels] = useState({ model_default: p.model_default, model_light: p.model_light });
  const [busy, setBusy] = useState(false);
  const [test, setTest] = useState<{ ok: boolean; text: string } | null>(null);
  const modelsChanged = models.model_default !== p.model_default || models.model_light !== p.model_light;

  async function save(patch: Patch, done: string) {
    setBusy(true);
    setTest(null);
    try {
      onSaved(await putJson<ProviderInfo>(`/api/agent/providers/${p.provider}`, patch));
      toast.success(done);
      return true;
    } catch (e) {
      toast.error(e instanceof ApiError ? `Couldn't save: ${e.detail}` : "Couldn't save.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function runTest() {
    setBusy(true);
    setTest(null);
    try {
      const r = await postJson<ProviderTest>(`/api/agent/providers/${p.provider}/test`);
      setTest({ ok: true, text: `${r.model} answered: ${r.reply || '(empty reply)'}` });
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail : 'Could not reach the server.';
      setTest({ ok: false, text: detail === 'no_key' ? 'No usable key: add one, and check the provider is enabled.' : detail });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-md border border-solid border-sf-line p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-display text-base text-sf-ink">{NAMES[p.provider] ?? p.provider}</span>
        <span className="flex items-center gap-3">
          <span className={`flex items-center gap-1.5 text-xs ${p.has_key ? 'text-sf-green-text' : 'text-sf-ink-dim'}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${p.has_key ? 'bg-sf-green' : 'bg-sf-ink-dim'}`} />
            {p.has_key ? 'Key saved' : 'No key'}
          </span>
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-sf-ink-mute">
            <input type="checkbox" checked={p.enabled} disabled={busy}
              onChange={e => void save({ enabled: e.target.checked }, e.target.checked ? 'Provider enabled.' : 'Provider disabled.')} />
            Enabled
          </label>
        </span>
      </div>

      <form className="flex flex-wrap items-end gap-2" onSubmit={e => {
        e.preventDefault();
        if (key.trim()) void save({ api_key: key.trim() }, 'Key saved.').then(ok => ok && setKey(''));
      }}>
        <label className={`${LABEL} flex-1`}>
          {p.has_key ? 'Replace the key' : 'API key'}
          <input type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} className={INPUT}
            placeholder={p.has_key ? 'A new key replaces the saved one' : 'Paste the key'} />
        </label>
        <button type="submit" disabled={busy || !key.trim()} className={PRIMARY}>Save key</button>
        {p.has_key && (
          <button type="button" disabled={busy} className={BUTTON} onClick={() => void save({ api_key: '' }, 'Key removed.')}>Remove key</button>
        )}
      </form>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <label className={LABEL}>
          Chat model
          <input value={models.model_default} onChange={e => setModels({ ...models, model_default: e.target.value })} className={INPUT} />
        </label>
        <label className={LABEL}>
          Light model (summaries, background)
          <input value={models.model_light} onChange={e => setModels({ ...models, model_light: e.target.value })} className={INPUT} />
        </label>
        <button type="button" disabled={busy || !modelsChanged || !models.model_default.trim() || !models.model_light.trim()} className={BUTTON}
          onClick={() => void save(models, 'Models saved.')}>Save models</button>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" disabled={busy} className={BUTTON} onClick={() => void runTest()}>Test</button>
        {test && (
          <span role="status" className={`min-w-0 break-words text-sm ${test.ok ? 'text-sf-green-text' : 'text-sf-red-text'}`}>{test.text}</span>
        )}
      </div>
    </div>
  );
}

/** Settings, AI: the providers Whisk can use (lifted in shape from CakeCRM's ProviderSetup). */
export default function ProvidersCard() {
  const { data, error, reload, setData } = useJson<ProviderInfo[]>('/api/agent/providers');
  if (error) return <LoadError label="Couldn't load the providers" onRetry={reload} />;
  if (!data) return <BootFallback variant="panel" />;
  return (
    <div className="flex flex-col gap-3">
      <p className={HINT}>
        Whisk uses the first enabled provider that has a key, in this order. Keys are stored encrypted and never shown again.
      </p>
      {data.map(p => (
        <ProviderRow key={p.provider} p={p} onSaved={next => setData(data.map(x => (x.provider === next.provider ? next : x)))} />
      ))}
    </div>
  );
}
