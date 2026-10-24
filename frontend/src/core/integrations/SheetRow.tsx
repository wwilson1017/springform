import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { api, patchJson } from '../api/client';
import { buttonClass, chipClass, errorText, errorTextClass, inputClass, labelClass, secondaryButtonClass } from '../settings/ui';
import { formatDate } from '../../shared/formatDate';
import { toast } from '../../shared/toast';
import type { Sheet, SheetSchedule } from './types';

type RefreshResult = { sheet: Sheet } | { retryAfter: number } | { error: string };

/**
 * POST /refresh. Its 429 carries `retry_after` (and a Retry-After header) that the countdown
 * needs, so this uses the typed client, which hands back the response rather than throwing.
 */
async function refreshSheet(id: number): Promise<RefreshResult> {
  try {
    const { data, error, response } = await api.POST('/api/core/sheets/{sheet_id}/refresh', { params: { path: { sheet_id: id } } });
    if (response.ok) return { sheet: data as Sheet };
    const body = (error ?? {}) as { detail?: unknown; retry_after?: number };
    if (response.status === 429) return { retryAfter: Number(response.headers.get('Retry-After')) || body.retry_after || 60 };
    return { error: typeof body.detail === 'string' ? body.detail : `Refresh failed (${response.status})` };
  } catch {
    return { error: "Couldn't reach the server. Try again." };
  }
}

/** A seconds countdown: `start(n)` begins it; it ticks once a second until it reaches zero. */
function useCountdown(): [number, (seconds: number) => void] {
  const [{ until, now }, set] = useState({ until: 0, now: 0 });
  useEffect(() => {
    if (now >= until) return;
    const timer = setTimeout(() => set(s => ({ ...s, now: Date.now() })), 1000);
    return () => clearTimeout(timer);
  }, [until, now]);
  const start = useCallback((seconds: number) => {
    const t = Date.now();
    set({ until: t + seconds * 1000, now: t });
  }, []);
  return [Math.max(0, Math.ceil((until - now) / 1000)), start];
}

interface Props {
  sheet: Sheet;
  onChange: (sheet: Sheet) => void;
  onReload: () => void;
  onPreview: () => void;
}

export function SheetRow({ sheet, onChange, onReload, onPreview }: Props) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [wait, startCountdown] = useCountdown();

  async function refresh() {
    setBusy(true);
    setMessage(null);
    const result = await refreshSheet(sheet.id);
    setBusy(false);
    if ('sheet' in result) {
      onChange(result.sheet);
      toast.success(`${sheet.name}: ${result.sheet.row_count ?? 0} rows fetched`);
    } else if ('retryAfter' in result) {
      startCountdown(result.retryAfter);
    } else {
      setMessage(result.error);
      onReload(); // a failed fetch is also recorded as the sheet's last_error
    }
  }

  const status = !sheet.configured ? 'Not set up' : sheet.last_error ? 'Error' : sheet.last_synced_at ? 'Synced' : 'Never synced';
  return (
    <li className="flex flex-col gap-2 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-sf-ink">{sheet.app} · {sheet.name}</span>
        <span className={chipClass}>{sheet.mode === 'read' ? 'Read' : 'Write'}</span>
        {!sheet.enabled && <span className={chipClass}>Off</span>}
        <span className={`${chipClass} ${sheet.last_error ? 'text-sf-red-text' : ''}`}>{status}</span>
      </div>
      {sheet.description && <p className="m-0 text-sm text-sf-ink-mute">{sheet.description}</p>}
      <dl className="m-0 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-xs">
        <dt className="text-sf-ink-dim">Spreadsheet</dt><dd className="m-0 break-all text-sf-ink">{sheet.spreadsheet_id || '—'}</dd>
        <dt className="text-sf-ink-dim">Range</dt><dd className="m-0 text-sf-ink">{sheet.range || '—'}</dd>
        <dt className="text-sf-ink-dim">Schedule</dt><dd className="m-0 text-sf-ink">{sheet.schedule}</dd>
        <dt className="text-sf-ink-dim">Last synced</dt><dd className="m-0 text-sf-ink">{sheet.last_synced_at ? formatDate(sheet.last_synced_at) : 'Never'}</dd>
        <dt className="text-sf-ink-dim">Rows</dt><dd className="m-0 text-sf-ink">{sheet.row_count ?? '—'}</dd>
        {sheet.last_error && <><dt className="text-sf-ink-dim">Last error</dt><dd className="m-0 break-words text-sf-red-text">{sheet.last_error}</dd></>}
      </dl>
      {editing ? (
        <SheetEditor sheet={sheet} onDone={s => { if (s) onChange(s); setEditing(false); }} />
      ) : (
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => setEditing(true)} className={secondaryButtonClass}>Edit</button>
          <button type="button" onClick={() => void refresh()} disabled={busy || wait > 0} className={secondaryButtonClass}>
            {wait > 0 ? `Refresh in ${wait}s` : busy ? 'Refreshing…' : 'Refresh'}
          </button>
          <button type="button" onClick={onPreview} className={secondaryButtonClass}>Preview</button>
        </div>
      )}
      {wait > 0 && <p role="status" className="m-0 text-xs text-sf-ink-mute">Refreshed less than a minute ago. Try again in {wait}s.</p>}
      {message && <p role="alert" className={errorTextClass}>{message}</p>}
    </li>
  );
}

function SheetEditor({ sheet, onDone }: { sheet: Sheet; onDone: (saved: Sheet | null) => void }) {
  const [spreadsheetId, setSpreadsheetId] = useState(sheet.spreadsheet_id);
  const [range, setRange] = useState(sheet.range);
  const [schedule, setSchedule] = useState<SheetSchedule>(sheet.schedule);
  const [enabled, setEnabled] = useState(sheet.enabled);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const id = `sheet-${sheet.id}`;

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onDone(await patchJson<Sheet>(`/api/core/sheets/${sheet.id}`, { spreadsheet_id: spreadsheetId, range, schedule, enabled }));
      toast.success(`${sheet.name} saved`);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="flex flex-col gap-3 rounded-md border border-sf-line p-3">
      <div>
        <label htmlFor={`${id}-ss`} className={labelClass}>Spreadsheet id or URL</label>
        <input id={`${id}-ss`} value={spreadsheetId} onChange={e => setSpreadsheetId(e.target.value)}
          placeholder="https://docs.google.com/spreadsheets/d/…" className={inputClass} />
      </div>
      <div className="flex flex-wrap gap-3">
        <div className="min-w-40 flex-1">
          <label htmlFor={`${id}-range`} className={labelClass}>Range</label>
          <input id={`${id}-range`} value={range} onChange={e => setRange(e.target.value)} placeholder="Sheet1!A1:F" className={inputClass} />
        </div>
        <div>
          <label htmlFor={`${id}-schedule`} className={labelClass}>Schedule</label>
          <select id={`${id}-schedule`} value={schedule} onChange={e => setSchedule(e.target.value as SheetSchedule)} className={inputClass}>
            <option value="hourly">Hourly</option>
            <option value="daily">Daily</option>
            <option value="manual">Manual</option>
          </select>
        </div>
      </div>
      <label className="flex items-center gap-2 text-sm text-sf-ink">
        <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} /> Enabled
      </label>
      {error && <p role="alert" className={errorTextClass}>{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={busy} className={buttonClass}>{busy ? 'Saving…' : 'Save'}</button>
        <button type="button" onClick={() => onDone(null)} className={secondaryButtonClass}>Cancel</button>
      </div>
    </form>
  );
}
