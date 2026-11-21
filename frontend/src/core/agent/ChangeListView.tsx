import { useEffect, useState } from 'react';
import { ApiError, postJson } from '../api/client';
import { useJson } from '../api/useJson';
import type { ChangeList } from './types';

const SHOWN = 20;

const value = (v: unknown) =>
  v === null || v === undefined || v === '' ? '—' : typeof v === 'string' ? v : JSON.stringify(v);

/**
 * The changes of one bulk run as the server read them (GET /api/agent/change-lists/{runId}):
 * "title · field: old → new", what the tool said beyond them, and, once applied, an Undo that
 * puts back every record nobody edited since. The parent remounts it (a `key`) when the run's
 * status changes, so a staged list reads again once applied. `onReady` fires when the list loaded.
 */
export function ChangeListView({ runId, onReady }: { runId: number; onReady?: () => void }) {
  const { data, error, setData } = useJson<ChangeList>(`/api/agent/change-lists/${runId}`);
  const [all, setAll] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    if (data) onReady?.();
  }, [data, onReady]);

  if (error) return <p className="mb-0 mt-2 text-sm text-sf-red-text">Could not load the changes.</p>;
  if (!data) return <p className="mb-0 mt-2 text-sm text-sf-ink-dim">Loading the changes…</p>;

  async function undo() {
    setBusy(true);
    setFailure(null);
    try {
      setData(await postJson<ChangeList>(`/api/agent/change-lists/${runId}/undo`));
    } catch (e) {
      setFailure(e instanceof ApiError ? `Undo failed: ${e.detail.replace(/_/g, ' ')}` : 'Undo failed; try again.');
    } finally {
      setBusy(false);
    }
  }

  const records = new Set(data.rows.map((r) => `${r.entity_type}:${r.entity_id}`)).size;
  const rows = all ? data.rows : data.rows.slice(0, SHOWN);
  return (
    <div className="mt-2 text-sm" data-testid="change-list">
      <p className="m-0 text-sf-ink">
        {data.rows.length} {data.rows.length === 1 ? 'change' : 'changes'} on {records}{' '}
        {records === 1 ? 'record' : 'records'}
        {data.hidden > 0 && `, and ${data.hidden} on records you can no longer see`}
      </p>
      {data.notes.length > 0 && (
        <ul className="mb-0 mt-1 pl-4 text-sf-amber-text">
          {data.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      <ul className="mb-0 mt-1 max-h-72 list-none overflow-auto rounded bg-sf-card p-2 font-mono text-xs text-sf-ink-mute">
        {rows.map((r, i) => (
          <li key={i} className="break-all">
            {r.title} · {r.field}: {value(r.old)} → {value(r.new)}
          </li>
        ))}
      </ul>
      {!all && data.rows.length > SHOWN && (
        <button
          type="button"
          onClick={() => setAll(true)}
          className="mt-1 cursor-pointer border-0 bg-transparent p-0 text-xs text-sf-accent"
        >
          Show all {data.rows.length}
        </button>
      )}
      {data.status === 'applied' && (
        <div className="mt-2 flex items-center gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => void undo()}
            className="cursor-pointer rounded border border-solid border-sf-line-strong bg-transparent px-3 py-1 text-sm text-sf-ink-mute disabled:cursor-default disabled:opacity-60"
          >
            {busy ? 'Undoing…' : 'Undo'}
          </button>
          {failure && (
            <span role="alert" className="text-sf-red-text">
              {failure}
            </span>
          )}
        </div>
      )}
      {data.status === 'undone' && (
        <div className="mt-2">
          <p className="m-0 text-sf-ink">Undone: {data.reverted} put back.</p>
          {data.skipped.length > 0 && (
            <ul className="mb-0 mt-1 pl-4 text-sf-ink-mute">
              {data.skipped.map((s) => (
                <li key={`${s.entity_type}:${s.entity_id}`}>
                  {s.title}: left as it is ({s.reason})
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
