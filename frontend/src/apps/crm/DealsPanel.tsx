/**
 * The Deals panel on a person's or an organization's page (registered for `core.person` and
 * `core.organization` in contributions.ts): their deals, open ones first, with a "New deal"
 * shortcut that pre-links the record. Loaded lazily by the record page.
 */
import { useState } from 'react';
import { Link } from 'react-router';
import type { RecordPanelProps } from '../../core/apps/types';
import { useJson } from '../../core/api/useJson';
import { LoadError } from '../../shared/LoadError';
import { recordDealsUrl, type Deal } from './api';
import { DealForm } from './components/DealForm';
import { StageBadge } from './components/badges';
import { formatCents } from './money';
import { btnLink, muted } from './ui';
import './theme.css';

export default function DealsPanel({ entityType, entityId }: RecordPanelProps) {
  const { data: deals, error, reload } = useJson<Deal[]>(recordDealsUrl(entityType, entityId));
  const isOrg = entityType === 'core.organization';
  // The record's name, so the new deal's picker shows it; a missing name still links by id.
  const record = useJson<{ name: string }>(`/api/core/contacts/${isOrg ? 'organizations' : 'people'}/${entityId}`).data;
  const [creating, setCreating] = useState(false);
  const ref = { id: entityId, name: record?.name ?? `#${entityId}` };

  return (
    <div className="flex flex-col gap-2">
      {error ? <LoadError label="Couldn't load deals" onRetry={reload} compact />
        : !deals ? <p className={muted}>Loading…</p>
        : deals.length === 0 ? <p className={muted}>No deals yet.</p>
        : (
          <ul className="m-0 list-none divide-y divide-sf-line p-0">
            {deals.map(d => (
              <li key={d.id}>
                <Link to={`/crm/deals/${d.id}`} className="flex items-center gap-3 py-2 text-sm no-underline">
                  <span className={`min-w-0 flex-1 truncate ${d.archived_at ? 'text-sf-ink-dim' : 'text-sf-ink'}`}>{d.title}</span>
                  <StageBadge stage={d.stage} />
                  <span className="text-sf-ink-mute">{formatCents(d.value_cents, d.currency)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      <button type="button" onClick={() => setCreating(true)} className={`${btnLink} self-start`}>New deal</button>
      {creating && (
        <DealForm person={isOrg ? null : ref} organization={isOrg ? ref : null}
          onClose={() => setCreating(false)} onCreated={() => { setCreating(false); reload(); }} />
      )}
    </div>
  );
}
