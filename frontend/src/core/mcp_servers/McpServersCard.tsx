import { useState, type FormEvent } from 'react';
import { ApiError, del, patchJson, postJson } from '../api/client';
import { useJson } from '../api/useJson';
import BootFallback from '../components/BootFallback';
import { confirmDialog } from '../../shared/confirm';
import { formatDate } from '../../shared/formatDate';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { suggestPrefix, validateDraft } from './form';
import type { McpServer, ServerDraft } from './types';

const BASE = '/api/core/mcp/servers';
const INPUT = 'w-full rounded-md border border-solid border-sf-line-strong bg-sf-card px-2.5 py-1.5 text-sm text-sf-ink placeholder:text-sf-ink-dim';
const LABEL = 'flex min-w-0 flex-col gap-1 text-xs text-sf-ink-dim';
const BUTTON = 'cursor-pointer rounded-md border border-solid border-sf-line-strong bg-transparent px-3 py-1.5 text-sm text-sf-ink-mute hover:text-sf-ink disabled:cursor-default disabled:opacity-50';
const PRIMARY = 'cursor-pointer rounded-md border-0 bg-sf-accent px-3 py-1.5 text-sm font-medium text-sf-accent-ink disabled:cursor-default disabled:opacity-50';
const EMPTY: ServerDraft = { name: '', url: '', token: '', prefix: '' };

function failure(e: unknown, what: string): string {
  if (e instanceof ApiError && e.status === 409) return 'That prefix is already used by another server.';
  if (e instanceof ApiError && e.status === 422) return `${what}: the server refused these settings. Use an https:// address.`;
  return e instanceof ApiError ? `${what}: ${e.detail}` : `${what}.`;
}

function ServerRow({ s, onChanged, onRemoved }: { s: McpServer; onChanged: (s: McpServer) => void; onRemoved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [test, setTest] = useState<{ ok: boolean; text: string } | null>(null);

  async function act(what: string, fn: () => Promise<void>) {
    setBusy(true);
    setTest(null);
    try {
      await fn();
    } catch (e) {
      toast.error(failure(e, what));
    } finally {
      setBusy(false);
    }
  }

  const toggle = () => act("Couldn't change the server", async () => {
    onChanged(await patchJson<McpServer>(`${BASE}/${s.id}`, { enabled: !s.enabled }));
  });
  const refresh = () => act("Couldn't refresh", async () => {
    const next = await postJson<McpServer>(`${BASE}/${s.id}/refresh`);
    onChanged(next);
    if (next.last_error) toast.error(`Discovery failed: ${next.last_error}`);
    else toast.success(`${next.name}: ${next.tools.length} tools.`);
  });
  const runTest = () => act("Couldn't test", async () => {
    const r = await postJson<{ ok: boolean; tools: number; error?: string }>(`${BASE}/${s.id}/test`);
    setTest(r.ok ? { ok: true, text: `Connected: ${r.tools} tools offered.` } : { ok: false, text: r.error ?? 'Failed.' });
  });
  const remove = async () => {
    const ok = await confirmDialog({
      title: 'Remove MCP server',
      message: `Whisk loses the tools from ${s.name}, and any approval still waiting for one of them will fail.`,
      confirmLabel: 'Remove', danger: true,
    });
    if (ok) await act("Couldn't remove the server", async () => { await del(`${BASE}/${s.id}`); onRemoved(); });
  };

  const status = !s.enabled ? 'Disabled' : s.last_error ? 'Not connected' : `${s.tools.length} tool${s.tools.length === 1 ? '' : 's'}`;
  const dot = !s.enabled ? 'bg-sf-ink-dim' : s.last_error ? 'bg-sf-red' : 'bg-sf-green';
  return (
    <li className="flex flex-col gap-2 rounded-md border border-solid border-sf-line p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex min-w-0 items-baseline gap-2">
          <span className="font-display text-base text-sf-ink">{s.name}</span>
          <code className="text-xs text-sf-ink-dim">{s.prefix}.*</code>
        </span>
        <label className="flex cursor-pointer items-center gap-1.5 text-xs text-sf-ink-mute">
          <input type="checkbox" checked={s.enabled} disabled={busy} onChange={() => void toggle()} />
          Enabled
        </label>
      </div>
      <code className="break-all text-xs text-sf-ink-soft">{s.url}</code>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-sf-ink-mute">
        <span className="flex items-center gap-1.5"><span className={`h-1.5 w-1.5 rounded-full ${dot}`} />{status}</span>
        <span>{s.last_discovered_at ? `Last discovered ${formatDate(s.last_discovered_at)}` : 'Never discovered'}</span>
        <span>{s.has_token ? 'Token saved' : 'No token'}</span>
      </div>
      {s.enabled && s.last_error && <p className="m-0 break-words text-sm text-sf-red-text">{s.last_error}</p>}
      {s.tools.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-sf-ink-mute">Tools</summary>
          <ul className="m-0 mt-2 flex list-none flex-col gap-1.5 p-0">
            {s.tools.map(t => (
              <li key={t.name} className="min-w-0">
                <code className="text-xs text-sf-ink">{s.prefix}.{t.name}</code>
                {t.read_only_hint && <span className="ml-2 text-xs text-sf-ink-dim">(says it is read-only)</span>}
                {t.description && <span className="block break-words text-xs text-sf-ink-soft">{t.description}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" disabled={busy || !s.enabled} className={BUTTON} onClick={() => void refresh()}>Refresh</button>
        <button type="button" disabled={busy} className={BUTTON} onClick={() => void runTest()}>Test</button>
        <button type="button" disabled={busy} className={BUTTON} onClick={() => void remove()}>Remove</button>
        {test && <span role="status" className={`min-w-0 break-words text-sm ${test.ok ? 'text-sf-green-text' : 'text-sf-red-text'}`}>{test.text}</span>}
      </div>
    </li>
  );
}

export function AddServerForm({ onAdded }: { onAdded: (s: McpServer) => void }) {
  const [draft, setDraft] = useState<ServerDraft>(EMPTY);
  const [prefixEdited, setPrefixEdited] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [busy, setBusy] = useState(false);
  const errors = validateDraft(draft);
  const shown = showErrors ? errors : {};

  function set(field: keyof ServerDraft, value: string) {
    if (field === 'prefix') setPrefixEdited(true);
    setDraft(d => ({ ...d, [field]: value, ...(field === 'name' && !prefixEdited ? { prefix: suggestPrefix(value) } : {}) }));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setShowErrors(true);
    if (Object.keys(errors).length) return;
    setBusy(true);
    try {
      const s = await postJson<McpServer>(BASE, { name: draft.name.trim(), url: draft.url.trim(), token: draft.token.trim(), prefix: draft.prefix });
      onAdded(s);
      setDraft(EMPTY);
      setPrefixEdited(false);
      setShowErrors(false);
      if (s.last_error) toast.error(`Added ${s.name}, but discovery failed: ${s.last_error}`);
      else toast.success(`Added ${s.name}: ${s.tools.length} tools.`);
    } catch (e) {
      toast.error(failure(e, "Couldn't add the server"));
    } finally {
      setBusy(false);
    }
  }

  const field = (key: keyof ServerDraft, label: string, extra: { placeholder?: string; type?: string } = {}) => (
    <div className="flex min-w-0 flex-col gap-1">
      <label className={LABEL}>
        {label}
        <input value={draft[key]} onChange={e => set(key, e.target.value)} className={INPUT} autoComplete="off"
          aria-invalid={shown[key] ? true : undefined} {...extra} />
      </label>
      {shown[key] && <span className="text-xs text-sf-red-text">{shown[key]}</span>}
    </div>
  );

  return (
    <form noValidate onSubmit={e => void submit(e)} className="flex flex-col gap-3 rounded-md border border-dashed border-sf-line-strong p-4">
      <span className="text-sm font-medium text-sf-ink">Add a server</span>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {field('name', 'Name', { placeholder: 'Team to-dos' })}
        {field('url', 'Address', { placeholder: 'https://example.com/mcp', type: 'url' })}
        {field('token', 'Token (optional)', { placeholder: 'Sent as a bearer token', type: 'password' })}
        {field('prefix', 'Prefix', { placeholder: 'todos' })}
      </div>
      <p className="m-0 text-xs text-sf-ink-dim">
        Whisk names this server's tools <code>{draft.prefix || 'prefix'}.tool_name</code>. The token is stored encrypted and never shown again.
      </p>
      <div><button type="submit" disabled={busy} className={PRIMARY}>{busy ? 'Connecting…' : 'Add server'}</button></div>
    </form>
  );
}

/** Settings, MCP servers: the other MCP servers Whisk may call (admin only). */
export default function McpServersCard() {
  const { data, error, reload, setData } = useJson<McpServer[]>(BASE);
  if (error) return <LoadError label="Couldn't load the MCP servers" onRetry={reload} />;
  if (!data) return <BootFallback variant="panel" />;
  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 text-sm text-sf-ink-soft">
        Whisk can call tools on other MCP servers. Every remote tool call asks for approval first, whatever the server
        says about the tool, and what comes back is treated as untrusted. These tools appear in every member's Whisk;
        each member approves their own calls.
      </p>
      {data.length === 0
        ? <p className="m-0 text-sm text-sf-ink-dim">No servers connected yet.</p>
        : (
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            {data.map(s => (
              <ServerRow key={s.id} s={s}
                onChanged={next => setData(data.map(x => (x.id === next.id ? next : x)))}
                onRemoved={() => setData(data.filter(x => x.id !== s.id))} />
            ))}
          </ul>
        )}
      <AddServerForm onAdded={s => setData([...data, s])} />
    </div>
  );
}
