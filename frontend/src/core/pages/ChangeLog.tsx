import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { formatDate } from '../../shared/formatDate';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { fetchJson } from '../api/client';
import type { UserRef } from '../api/types';
import { useJson } from '../api/useJson';
import { useCoreApps } from '../apps/CoreAppsContext';
import { useAuth } from '../auth/AuthContext';
import { appName, CORE_LABEL, formatValue } from './format';
import { Chip, inputClass, Page, quietButtonClass } from './Page';
import type { ChangeRow } from './types';

/** Query params the page reads and passes through, so a record page can deep-link
 * `/changelog?entity_type=…&entity_id=…`. `limit` is the page size (default 50, the route's). */
const FILTERS = ['app', 'user_id', 'entity_type', 'entity_id'] as const;
type Filter = typeof FILTERS[number];

export function ChangeLogPage() {
  const { isAdmin } = useAuth();
  const { apps } = useCoreApps();
  const [params, setParams] = useSearchParams();
  const limit = Math.min(200, Math.max(1, Number(params.get('limit')) || 50));
  const filters = new URLSearchParams();
  for (const key of FILTERS) {
    const value = params.get(key)?.trim();
    if (value) filters.set(key, value);
  }
  filters.set('limit', String(limit));
  const query = filters.toString();

  const first = useJson<ChangeRow[]>(`/api/core/changelog?${query}`);
  // Pages fetched with "Show older", kept only while the filters that produced them hold.
  const [older, setOlder] = useState<{ query: string; rows: ChangeRow[]; done: boolean } | null>(null);
  const extra = older?.query === query ? older : null;
  const rows = first.data ? [...first.data, ...(extra?.rows ?? [])] : null;
  const done = extra ? extra.done : (first.data?.length ?? 0) < limit;
  const [loadingOlder, setLoadingOlder] = useState(false);

  // Admins pick from every user; a member picks from the people in the rows on screen.
  const allUsers = useJson<UserRef[]>(isAdmin ? '/api/auth/users' : null);
  const userOptions = new Map<number, string>();
  for (const u of allUsers.data ?? rows?.map(r => r.user).filter(u => u !== null) ?? []) userOptions.set(u.id, u.name);
  const selectedUser = Number(params.get('user_id'));
  if (selectedUser && !userOptions.has(selectedUser)) userOptions.set(selectedUser, `User #${selectedUser}`);

  function setFilter(key: Filter, value: string) {
    setParams(prev => {
      const next = new URLSearchParams(prev);
      if (value) next.set(key, value);
      else next.delete(key);
      return next;
    }, { replace: true });
  }

  async function showOlder() {
    if (!rows?.length) return;
    setLoadingOlder(true);
    try {
      const page = await fetchJson<ChangeRow[]>(`/api/core/changelog?${query}&before=${rows[rows.length - 1].id}`);
      setOlder({ query, rows: [...(extra?.rows ?? []), ...page], done: page.length < limit });
    } catch {
      toast.error("Couldn't load older changes.");
    } finally {
      setLoadingOlder(false);
    }
  }

  const filtered = FILTERS.some(k => params.get(k));
  const textFilter = (key: 'entity_type' | 'entity_id', label: string, placeholder: string) => (
    <label className="flex flex-col gap-1 text-xs text-sf-ink-dim">
      {label}
      {/* Uncontrolled and keyed on the URL: typing never fetches; Enter or leaving the field applies it. */}
      <input key={params.get(key) ?? ''} defaultValue={params.get(key) ?? ''} placeholder={placeholder}
        inputMode={key === 'entity_id' ? 'numeric' : undefined} className={`${inputClass} w-full`}
        onBlur={e => { if (e.target.value.trim() !== (params.get(key) ?? '')) setFilter(key, e.target.value.trim()); }}
        onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur(); }} />
    </label>
  );

  return (
    <Page title="Change log" intro="Every field change to the records you can open, newest first.">
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-[1fr_1fr_1fr_8rem_auto] md:items-end">
        <label className="flex flex-col gap-1 text-xs text-sf-ink-dim">
          App
          <select value={params.get('app') ?? ''} onChange={e => setFilter('app', e.target.value)} className={`${inputClass} w-full`}>
            <option value="">All apps</option>
            <option value="core">{CORE_LABEL}</option>
            {(apps ?? []).map(a => <option key={a.slug} value={a.slug}>{a.name}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-sf-ink-dim">
          User
          <select value={params.get('user_id') ?? ''} onChange={e => setFilter('user_id', e.target.value)} className={`${inputClass} w-full`}>
            <option value="">Everyone</option>
            {[...userOptions].map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label>
        {textFilter('entity_type', 'Record type', 'Any')}
        {textFilter('entity_id', 'Record id', 'Any')}
        {filtered && (
          <button type="button" onClick={() => setParams(new URLSearchParams(), { replace: true })} className={`${quietButtonClass} col-span-2 md:col-span-1`}>
            Clear filters
          </button>
        )}
      </div>

      {first.error ? <LoadError label="Couldn't load the change log" onRetry={first.reload} />
        : !rows ? <p className="text-sm text-sf-ink-dim">Loading…</p>
        : rows.length === 0 ? <p className="text-sm text-sf-ink-dim">{filtered ? 'No changes match these filters.' : 'No changes yet.'}</p>
        : (
          <>
            <ul className="m-0 list-none divide-y divide-sf-line rounded-lg border border-sf-line-strong bg-sf-card p-0">
              {rows.map(r => <ChangeItem key={r.id} row={r} app={appName(apps, r.app)} />)}
            </ul>
            <div className="mt-4 text-center">
              {done ? <p className="m-0 text-xs text-sf-ink-dim">That's the oldest change{filtered ? ' for these filters' : ''}.</p>
                : <button type="button" onClick={() => void showOlder()} disabled={loadingOlder} className={quietButtonClass}>
                  {loadingOlder ? 'Loading…' : 'Show older'}
                </button>}
            </div>
          </>
        )}
    </Page>
  );
}

function ChangeItem({ row, app }: { row: ChangeRow; app: string }) {
  const label = row.title ?? `${row.entity_type} #${row.entity_id}`;
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        {row.url ? <Link to={row.url} className="text-sm font-medium text-sf-ink no-underline hover:underline">{label}</Link>
          : <span className="text-sm font-medium text-sf-ink-mute">{label}</span>}
        {row.title === null && <Chip tone="red">deleted</Chip>}
        <Chip>{app}</Chip>
      </div>
      <div className="mt-1 text-sm break-words text-sf-ink-mute">
        <span className="text-sf-ink-soft">{row.field}:</span>{' '}
        <span className="text-sf-ink-dim">{formatValue(row.old)}</span> → <span className="text-sf-ink">{formatValue(row.new)}</span>
      </div>
      {row.reason && <div className="mt-1 text-sm text-sf-ink-soft italic">{row.reason}</div>}
      <div className="mt-1 text-xs text-sf-ink-dim">{row.user?.name ?? 'System'} · {formatDate(row.at)}</div>
    </li>
  );
}
