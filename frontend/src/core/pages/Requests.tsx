import { useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { formatDate } from '../../shared/formatDate';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { ApiError, postJson } from '../api/client';
import { useJson } from '../api/useJson';
import { useCoreApps } from '../apps/CoreAppsContext';
import { useAuth } from '../auth/AuthContext';
import { appName } from './format';
import { buttonClass, Chip, inputClass, Page, quietButtonClass } from './Page';
import type { RequestRow, RequestsConfig } from './types';

type Tab = 'open' | 'closed' | 'all';
const TABS: Array<[Tab, string]> = [['open', 'Open'], ['closed', 'Closed'], ['all', 'All']];
/** Every request carries these two labels, so a chip for them says nothing. */
const hiddenLabel = (l: string) => l === 'request' || l.startsWith('app:');

export function RequestsPage() {
  const { isAdmin } = useAuth();
  const { apps } = useCoreApps();
  const config = useJson<RequestsConfig>('/api/core/requests/config');
  const [tab, setTab] = useState<Tab>('open');
  // simplification: the newest 200 per tab (the route's cap); add offset paging past that.
  const board = useJson<RequestRow[]>(`/api/core/requests?state=${tab}&limit=200`);
  const [formOpen, setFormOpen] = useState(false);
  const [created, setCreated] = useState<RequestRow | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  async function refresh() {
    setRefreshing(true);
    try {
      const { updated } = await postJson<{ updated: number }>('/api/core/requests/refresh');
      toast.success(updated ? `Updated ${updated} request${updated === 1 ? '' : 's'} from GitHub.` : 'The board is up to date.');
      board.reload();
    } catch (e) {
      toast.error(e instanceof ApiError && e.detail === 'github_not_configured'
        ? "GitHub isn't connected, so there is nothing to refresh." : "Couldn't refresh from GitHub.");
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <Page title="Requests" intro="Ask for a change or a new feature, then follow it here."
      actions={
        <div className="flex gap-2">
          {isAdmin && <button type="button" onClick={() => void refresh()} disabled={refreshing} className={quietButtonClass}>Refresh</button>}
          {!formOpen && <button type="button" onClick={() => { setFormOpen(true); setCreated(null); }} className={buttonClass}>New request</button>}
        </div>
      }>
      {config.data && !config.data.configured && <div className="mb-4"><NotConnected isAdmin={isAdmin} /></div>}

      {created && (
        <div role="status" className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-sf-green/40 bg-sf-green/8 px-4 py-3 text-sm text-sf-ink">
          Request sent{created.issue_number != null && <> as #{created.issue_number}</>}.
          {created.url && <a href={created.url} target="_blank" rel="noopener noreferrer" className="text-sf-accent-text">View it on GitHub</a>}
        </div>
      )}

      {formOpen && config.data && (
        <RequestForm config={config.data} isAdmin={isAdmin}
          appOptions={(apps ?? []).map(a => [a.slug, a.name])}
          onCancel={() => setFormOpen(false)}
          onCreated={row => { setCreated(row); setFormOpen(false); setTab('open'); board.reload(); }} />
      )}

      <div role="tablist" aria-label="Request state" className="mb-3 flex gap-1 border-b border-sf-line">
        {TABS.map(([value, label]) => (
          <button key={value} type="button" role="tab" aria-selected={tab === value} onClick={() => setTab(value)}
            className={`-mb-px cursor-pointer border-0 border-b-2 bg-transparent px-3 py-2 font-sans text-sm ${
              tab === value ? 'border-sf-accent text-sf-ink' : 'border-transparent text-sf-ink-soft hover:text-sf-ink'}`}>
            {label}
          </button>
        ))}
      </div>

      {board.error ? <LoadError label="Couldn't load requests" onRetry={board.reload} />
        : !board.data ? <p className="text-sm text-sf-ink-dim">Loading…</p>
        : board.data.length === 0 ? <p className="text-sm text-sf-ink-dim">No {tab === 'all' ? '' : `${tab} `}requests.</p>
        : (
          <ul className="m-0 list-none divide-y divide-sf-line rounded-lg border border-sf-line-strong bg-sf-card p-0">
            {board.data.map(r => (
              <li key={r.id} className={`px-4 py-3 ${r.id === created?.id ? 'bg-sf-green/8' : ''}`}>
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  {r.url
                    ? <a href={r.url} target="_blank" rel="noopener noreferrer" className="text-sm font-medium text-sf-ink no-underline hover:underline">{r.title}</a>
                    : <span className="text-sm font-medium text-sf-ink">{r.title}</span>}
                  {r.issue_number != null && <span className="text-xs text-sf-ink-dim">#{r.issue_number}</span>}
                  {tab === 'all' && <Chip tone={r.state === 'open' ? 'green' : 'plain'}>{r.state}</Chip>}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-sf-ink-dim">
                  <Chip>{appName(apps, r.app)}</Chip>
                  {r.labels.filter(l => !hiddenLabel(l)).map(l => <Chip key={l} tone="amber">{l}</Chip>)}
                  <span>{r.requested_by?.name ?? 'Unknown'} · {formatDate(r.created_at)}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
    </Page>
  );
}

function NotConnected({ isAdmin, notSent }: { isAdmin: boolean; notSent?: boolean }) {
  return (
    <p role={notSent ? 'alert' : undefined} className="m-0 rounded-lg border border-sf-amber/40 bg-sf-amber/10 px-4 py-3 text-sm text-sf-ink">
      {notSent && <strong className="font-medium">Not sent. </strong>}
      Requests aren't connected to GitHub yet, so new ones can't be sent.{' '}
      {isAdmin
        ? <>Add the repository and a token in <Link to="/settings/integrations" className="text-sf-accent-text">Settings → Integrations</Link>.</>
        : 'Ask an admin to connect it.'}
    </p>
  );
}

function sendError(e: unknown): string {
  if (!(e instanceof ApiError)) return "Couldn't reach the server. Check the board before sending it again.";
  if (e.status === 422) return `Check the form: ${e.detail}.`;
  if (e.status === 502) return "GitHub didn't accept the request, so it may not have been filed. Check the board before sending it again.";
  return "Couldn't send the request.";
}

function RequestForm({ config, isAdmin, appOptions, onCancel, onCreated }: {
  config: RequestsConfig;
  isAdmin: boolean;
  appOptions: Array<[string, string]>;
  onCancel: () => void;
  onCreated: (row: RequestRow) => void;
}) {
  const [title, setTitle] = useState('');
  const [app, setApp] = useState('core');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  // 'not_configured', or a sentence to show.
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onCreated(await postJson<RequestRow>('/api/core/requests', { title: title.trim(), app, description: description.trim() }));
    } catch (err) {
      setError(err instanceof ApiError && err.status === 409 && err.detail === 'github_not_configured' ? 'not_configured' : sendError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} aria-label="New request" className="mb-6 flex flex-col gap-3 rounded-lg border border-sf-line-strong bg-sf-card p-4">
      <h2 className="m-0 font-display text-base font-medium text-sf-ink">New request</h2>
      {config.warning_text && <p className="m-0 rounded-md bg-sf-amber/10 px-3 py-2 text-sm text-sf-ink-mute">{config.warning_text}</p>}
      <label className="flex flex-col gap-1 text-sm text-sf-ink-mute">
        Title
        <input value={title} onChange={e => setTitle(e.target.value)} maxLength={200} required
          placeholder="Show the delivery date on the order list" className={inputClass} />
      </label>
      <label className="flex flex-col gap-1 text-sm text-sf-ink-mute">
        About
        <select value={app} onChange={e => setApp(e.target.value)} className={inputClass}>
          <option value="core">Core platform</option>
          {appOptions.map(([slug, name]) => <option key={slug} value={slug}>{name}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-sm text-sf-ink-mute">
        Description
        <textarea value={description} onChange={e => setDescription(e.target.value)} maxLength={10000} rows={5}
          placeholder="What you need and why. Examples help." className={inputClass} />
      </label>
      {error === 'not_configured' ? <NotConnected isAdmin={isAdmin} notSent />
        : error && <p role="alert" className="m-0 text-sm text-sf-red-text">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={busy || !title.trim()} className={buttonClass}>{busy ? 'Sending…' : 'Send request'}</button>
        <button type="button" onClick={onCancel} className={quietButtonClass}>Cancel</button>
      </div>
    </form>
  );
}
