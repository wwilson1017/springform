import { useState, type FormEvent } from 'react';
import { ApiError, del, postJson } from '../api/client';
import { useJson } from '../api/useJson';
import { confirmDialog } from '../../shared/confirm';
import { formatDate } from '../../shared/formatDate';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { CLIENTS, type ClientSetup } from './clients';
import type { McpLink, NewMcpLink } from './types';
import { useAgentName } from '../agent/useAgentName';

const LINKS = '/api/core/mcp/links';
const inputClass =
  'min-w-0 flex-1 rounded-md border border-sf-line-strong bg-sf-card px-3 py-2 text-sm text-sf-ink placeholder:text-sf-ink-dim';
const primaryClass =
  'cursor-pointer rounded-md border-0 bg-sf-accent px-4 py-2 text-sm font-medium text-sf-accent-ink disabled:opacity-50';
const secondaryClass =
  'cursor-pointer rounded-md border border-sf-line-strong bg-transparent px-3 py-1.5 text-sm text-sf-ink hover:bg-sf-hover';
const codeClass = 'block break-all rounded bg-sf-raised px-2 py-1.5 font-mono text-xs text-sf-ink';

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success('Copied.');
  } catch {
    toast.error("Couldn't copy. Select the text and copy it yourself.");
  }
}

/**
 * The signed-in user's MCP links (docs/agents/mcp.md §1). A new link's URL lives only in this
 * component's state: "Done", revoking it or leaving the page forgets it, and the list never has it.
 */
export default function McpLinksCard() {
  const agentName = useAgentName();
  const { data: links, error, reload } = useJson<McpLink[]>(LINKS);
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [fresh, setFresh] = useState<NewMcpLink | null>(null);

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      setFresh(await postJson<NewMcpLink>(LINKS, { label: label.trim() }));
      setLabel('');
      reload();
    } catch (err) {
      toast.error(
        err instanceof ApiError && err.status < 500
          ? `Couldn't create the link: ${err.detail}`
          : "Couldn't create the link.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function revoke(link: McpLink) {
    const ok = await confirmDialog({
      title: 'Revoke link',
      message: `Anything connected with “${link.label}” stops working at once. This can't be undone.`,
      confirmLabel: 'Revoke',
      danger: true,
    });
    if (!ok) return;
    try {
      await del(`${LINKS}/${link.id}`);
      if (fresh?.id === link.id) setFresh(null);
      reload();
    } catch {
      toast.error("Couldn't revoke the link.");
    }
  }

  return (
    <div className="flex flex-col gap-4 text-sm">
      <p className="m-0 text-sf-ink-mute">
        Connect an AI tool (Claude, ChatGPT, Gemini, Cursor, VS Code, Codex and others) to this workspace. It gets the
        same tools {agentName} has and acts as you, so a link is as private as your password: make one per app, and
        revoke any you stop using.
      </p>

      <form onSubmit={create} className="flex flex-wrap gap-2">
        <label htmlFor="mcp-link-label" className="sr-only">
          Link name
        </label>
        <input
          id="mcp-link-label"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          maxLength={80}
          placeholder="e.g. Claude Desktop"
          className={inputClass}
        />
        <button type="submit" disabled={busy || !label.trim()} className={primaryClass}>
          Create link
        </button>
      </form>

      {fresh && <NewLink link={fresh} onDone={() => setFresh(null)} />}

      {error ? (
        <LoadError label="Couldn't load your links" onRetry={reload} compact />
      ) : !links ? (
        <p className="m-0 text-sf-ink-dim">Loading…</p>
      ) : links.length === 0 ? (
        <p className="m-0 text-sf-ink-dim">No links yet.</p>
      ) : (
        <ul aria-label="Your MCP links" className="m-0 list-none divide-y divide-sf-line p-0">
          {links.map((link) => (
            <li key={link.id} className="flex items-center gap-3 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="truncate text-sf-ink">{link.label}</div>
                <div className="text-xs text-sf-ink-dim">
                  {link.last_used_at ? `Last used ${formatDate(link.last_used_at)}` : 'Never used'}
                  {' · '}made {formatDate(link.created_at)}
                </div>
              </div>
              <button
                type="button"
                onClick={() => revoke(link)}
                aria-label={`Revoke ${link.label}`}
                className={secondaryClass}
              >
                Revoke
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function NewLink({ link, onDone }: { link: NewMcpLink; onDone: () => void }) {
  const [tab, setTab] = useState(CLIENTS[0].name);
  const client = CLIENTS.find((c) => c.name === tab) ?? CLIENTS[0];
  return (
    <div role="region" aria-label="New link" className="rounded-md border border-sf-line-strong bg-sf-raised/40 p-4">
      <p className="m-0 mb-2 font-medium text-sf-ink">“{link.label}” is ready. Copy it now: it won't be shown again.</p>
      <div className="flex flex-wrap items-center gap-2">
        <code data-testid="mcp-new-url" className={`${codeClass} min-w-0 flex-1`}>
          {link.url}
        </code>
        <button type="button" onClick={() => copy(link.url)} className={secondaryClass}>
          Copy link
        </button>
      </div>
      <div role="tablist" aria-label="Connect with" className="mt-4 flex flex-wrap gap-1.5">
        {CLIENTS.map((c) => (
          <button
            key={c.name}
            type="button"
            role="tab"
            aria-selected={tab === c.name}
            onClick={() => setTab(c.name)}
            className={`cursor-pointer rounded-full border-0 px-3 py-1 text-sm ${tab === c.name ? 'bg-sf-accent text-sf-accent-ink' : 'bg-sf-hover text-sf-ink-mute hover:text-sf-ink'}`}
          >
            {c.name}
          </button>
        ))}
      </div>
      <div role="tabpanel" aria-label={client.name} className="mt-3">
        <Steps client={client} url={link.url} />
      </div>
      <button type="button" onClick={onDone} className={`${primaryClass} mt-4`}>
        Done
      </button>
    </div>
  );
}

function Steps({ client, url }: { client: ClientSetup; url: string }) {
  const command = client.command?.(url);
  return (
    <div className="flex flex-col gap-2 text-sf-ink-mute">
      {client.note && <p className="m-0 text-xs text-sf-ink-dim">{client.note}</p>}
      {client.steps && (
        <ol className="m-0 flex list-decimal flex-col gap-1 pl-5">
          {client.steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      )}
      {client.deeplink && (
        <a href={client.deeplink(url)} className={`${secondaryClass} self-start no-underline`}>
          Add to {client.name}
        </a>
      )}
      {command && (
        <div>
          {client.commandLabel && <p className="m-0 mb-1 text-xs text-sf-ink-dim">{client.commandLabel}</p>}
          <span className="flex flex-wrap items-center gap-2">
            <code className={`${codeClass} min-w-0 flex-1`}>{command}</code>
            <button type="button" onClick={() => copy(command)} className={secondaryClass}>
              Copy command
            </button>
          </span>
        </div>
      )}
    </div>
  );
}
