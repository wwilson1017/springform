import { useEffect } from 'react';
import { useJson } from '../api/useJson';
import BootFallback from '../components/BootFallback';
import { chipClass } from '../settings/ui';
import { formatDate } from '../../shared/formatDate';
import { IconX } from '../../shared/icons';
import { LoadError } from '../../shared/LoadError';
import type { Sheet, SheetPreview } from './types';

/** The cached header and first 20 rows of one sheet, in a panel over the page. Escape closes it. */
export function SheetPreviewDrawer({ sheet, onClose }: { sheet: Sheet; onClose: () => void }) {
  const { data, error, reload } = useJson<SheetPreview>(`/api/core/sheets/${sheet.id}/preview`);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-sf-scrim" onClick={onClose} />
      <div role="dialog" aria-modal="true" aria-label={`Preview of ${sheet.name}`}
        className="relative flex h-full w-full max-w-3xl flex-col bg-sf-card shadow-lg">
        <div className="flex items-center gap-3 border-b border-sf-line px-5 py-3">
          <h2 className="m-0 flex-1 font-display text-base font-medium text-sf-ink">{sheet.app} · {sheet.name}</h2>
          <button type="button" aria-label="Close preview" onClick={onClose} className="cursor-pointer border-0 bg-transparent p-1 text-sf-ink-mute">
            <IconX aria-hidden />
          </button>
        </div>
        <div className="flex-1 overflow-auto px-5 py-4">
          {error ? <LoadError label="Couldn't load the preview" onRetry={reload} /> : !data ? <BootFallback variant="panel" /> : (
            <>
              <p className="m-0 mb-3 flex flex-wrap items-center gap-2 text-xs text-sf-ink-mute">
                {data.fetched_at ? `Fetched ${formatDate(data.fetched_at)}` : 'Never fetched'}
                {data.row_count != null && <span>· {data.row_count} rows, first {data.rows.length} shown</span>}
                {data.stale && <span className={`${chipClass} text-sf-amber-text`} title="No cache yet, the last refresh failed, or the cache is older than twice its schedule">Stale</span>}
              </p>
              {data.header.length === 0 ? (
                <p className="m-0 text-sm text-sf-ink-mute">Nothing cached yet. Set the spreadsheet and range, then refresh.</p>
              ) : (
                <table className="border-collapse text-xs">
                  <thead>
                    <tr>{data.header.map((h, i) => <th key={i} className="whitespace-nowrap border border-sf-line bg-sf-raised px-2 py-1 text-left font-medium text-sf-ink">{h}</th>)}</tr>
                  </thead>
                  <tbody>
                    {data.rows.map((row, r) => (
                      <tr key={r}>{row.map((cell, c) => <td key={c} className="whitespace-nowrap border border-sf-line px-2 py-1 text-sf-ink-mute">{cell}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
