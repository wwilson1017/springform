import { useState, type FormEvent } from 'react';
import { ApiError, del, postJson } from '../api/client';
import { useJson } from '../api/useJson';
import { confirmDialog } from '../../shared/confirm';
import { formatDate } from '../../shared/formatDate';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import type { McpLink, NewMcpLink } from './types';

const LINKS = '/api/core/mcp/links';
const inputClass = 'min-w-0 flex-1 rounded-md border border-sf-line-strong bg-sf-card px-3 py-2 text-sm text-sf-ink placeholder:text-sf-ink-dim';
const primaryClass = 'cursor-pointer rounded-md border-0 bg-sf-accent px-4 py-2 text-sm font-medium text-sf-accent-ink disabled:opacity-50';
const secondaryClass = 'cursor-pointer rounded-md border border-sf-line-strong bg-transparent px-3 py-1.5 text-sm text-sf-ink hover:bg-sf-hover';
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
      toast.error(err instanceof ApiError && err.status < 500 ? `Couldn't create the link: ${err.detail}` : "Couldn't create the link.");
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
        Connect Claude (claude.ai, Claude Desktop or Claude Code) to this workspace. It gets the same tools
        Whisk has and acts as you, so a link is as private as your password: make one per app, and revoke
        any you stop using.
      </p>

      <form onSubmit={create} className="flex flex-wrap gap-2">
        <label htmlFor="mcp-link-label" className="sr-only">Link name</label>
        <input id="mcp-link-label" value={label} onChange={e => setLabel(e.target.value)} maxLength={80}
          placeholder="e.g. Claude Desktop" className={inputClass} />
        <button type="submit" disabled={busy || !label.trim()} className={primaryClass}>Create link</button>
      </form>

      {fresh && <NewLink link={fresh} onDone={() => setFresh(null)} />}

      {error ? <LoadError label="Couldn't load your links" onRetry={reload} compact />
        : !links ? <p className="m-0 text-sf-ink-dim">Loading…</p>
        : links.length === 0 ? <p className="m-0 text-sf-ink-dim">No links yet.</p>
        : (
          <ul aria-label="Your MCP links" className="m-0 list-none divide-y divide-sf-line p-0">
            {links.map(link => (
              <li key={link.id} className="flex items-center gap-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sf-ink">{link.label}</div>
                  <div className="text-xs text-sf-ink-dim">
                    {link.last_used_at ? `Last used ${formatDate(link.last_used_at)}` : 'Never used'}
                    {' · '}made {formatDate(link.created_at)}
                  </div>
                </div>
                <button type="button" onClick={() => revoke(link)} aria-label={`Revoke ${link.label}`} className={secondaryClass}>
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
  const command = `claude mcp add --transport http springform ${link.url}`;
  return (
    <div role="region" aria-label="New link" className="rounded-md border border-sf-line-strong bg-sf-raised/40 p-4">
      <p className="m-0 mb-2 font-medium text-sf-ink">“{link.label}” is ready. Copy it now: it won't be shown again.</p>
      <div className="flex flex-wrap items-center gap-2">
        <code data-testid="mcp-new-url" className={`${codeClass} min-w-0 flex-1`}>{link.url}</code>
        <button type="button" onClick={() => copy(link.url)} className={secondaryClass}>Copy link</button>
      </div>
      <ul className="mb-0 mt-3 flex list-none flex-col gap-2 p-0 text-sf-ink-mute">
        <li><span className="text-sf-ink">claude.ai:</span> Settings → Connectors → Add custom connector, and paste the link as its URL.</li>
        <li><span className="text-sf-ink">Claude Desktop:</span> Settings → Connectors → Add custom connector, and paste the link.</li>
        <li>
          <span className="text-sf-ink">Claude Code:</span> run
          <span className="mt-1 flex flex-wrap items-center gap-2">
            <code className={`${codeClass} min-w-0 flex-1`}>{command}</code>
            <button type="button" onClick={() => copy(command)} className={secondaryClass}>Copy command</button>
          </span>
        </li>
      </ul>
      <button type="button" onClick={onDone} className={`${primaryClass} mt-4`}>Done</button>
    </div>
  );
}
