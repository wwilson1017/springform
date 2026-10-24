import { useState } from 'react';
import { ApiError, patchJson } from '../api/client';
import { useJson } from '../api/useJson';
import BootFallback from '../components/BootFallback';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import type { AgentRow } from './types';
import { HINT, INPUT, LABEL, PRIMARY } from './ui';

function AgentForm({ agent, onSaved }: { agent: AgentRow; onSaved: (a: AgentRow) => void }) {
  const [form, setForm] = useState({
    name: agent.name, personality: agent.personality, provider_override: agent.provider_override ?? '',
    model_override: agent.model_override ?? '', model_tier: agent.model_tier,
  });
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<typeof form>) => setForm(f => ({ ...f, ...patch }));

  async function save() {
    setBusy(true);
    try {
      onSaved(await patchJson<AgentRow>(`/api/agent/agents/${agent.slug}`, {
        name: form.name.trim(), personality: form.personality, model_tier: form.model_tier,
        // Blank means "use the install's choice", which the server stores as null.
        provider_override: form.provider_override || null, model_override: form.model_override.trim() || null,
      }));
      toast.success(`${form.name.trim()} saved.`);
    } catch (e) {
      toast.error(e instanceof ApiError ? `Couldn't save: ${e.detail}` : "Couldn't save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="flex flex-col gap-3" onSubmit={e => { e.preventDefault(); void save(); }}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className={LABEL}>
          Name
          <input required maxLength={80} value={form.name} onChange={e => set({ name: e.target.value })} className={INPUT} />
        </label>
        <label className={LABEL}>
          Model tier
          <select value={form.model_tier} onChange={e => set({ model_tier: e.target.value as AgentRow['model_tier'] })} className={INPUT}>
            <option value="default">Chat model (default)</option>
            <option value="light">Light model (cheaper, faster)</option>
          </select>
        </label>
        <label className={LABEL}>
          Provider
          <select value={form.provider_override} onChange={e => set({ provider_override: e.target.value })} className={INPUT}>
            <option value="">The install's first usable provider</option>
            <option value="anthropic">Anthropic</option>
            <option value="openai">OpenAI</option>
          </select>
        </label>
        <label className={LABEL}>
          Model override
          <input maxLength={200} value={form.model_override} onChange={e => set({ model_override: e.target.value })} className={INPUT}
            placeholder="Blank: the tier's model" />
        </label>
      </div>
      <label className={LABEL}>
        Personality (added to the system prompt)
        <textarea rows={4} maxLength={20000} value={form.personality} onChange={e => set({ personality: e.target.value })}
          className={`${INPUT} resize-y`} placeholder="Tone, habits, things to always or never do" />
      </label>
      <div><button type="submit" disabled={busy || !form.name.trim()} className={PRIMARY}>Save</button></div>
    </form>
  );
}

/** Settings, AI: the agent roster (today just Whisk): name, personality, provider and model. */
export default function AgentsCard() {
  const { data, error, reload, setData } = useJson<AgentRow[]>('/api/agent/agents');
  if (error) return <LoadError label="Couldn't load the agents" onRetry={reload} />;
  if (!data) return <BootFallback variant="panel" />;
  return (
    <div className="flex flex-col gap-5">
      <p className={HINT}>The model override applies only when the chosen provider is the one in use.</p>
      {data.map(a => (
        <section key={a.slug} aria-label={a.name} className="flex flex-col gap-2">
          {data.length > 1 && <h3 className="m-0 text-sm font-medium text-sf-ink">{a.name}</h3>}
          <AgentForm agent={a} onSaved={next => setData(data.map(x => (x.slug === next.slug ? next : x)))} />
        </section>
      ))}
    </div>
  );
}
