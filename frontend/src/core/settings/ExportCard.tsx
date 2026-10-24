import { Link } from 'react-router';
import { useJson } from '../api/useJson';
import BootFallback from '../components/BootFallback';
import { LoadError } from '../../shared/LoadError';

interface ExportPreview {
  tables: Array<{ name: string; columns: string[]; estimated_rows: number }>;
}

/** The business-data export: what the ZIP holds, and the download. */
export default function ExportCard() {
  const { data, error, reload } = useJson<ExportPreview>('/api/core/export/preview');
  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 text-sm text-sf-ink-mute">
        A ZIP with one CSV per table. Passwords, sign-in secrets, stored keys and Whisk conversations are never
        included, and rows you cannot see on screen (someone else's private to-dos) are left out. For a full copy of
        the install, use <Link to="/backups" className="text-sf-accent-text">Backups</Link>.
      </p>
      <div><a href="/api/core/export" download className="inline-block rounded-md bg-sf-accent px-3.5 py-2 text-sm font-medium text-sf-accent-ink no-underline">Download ZIP</a></div>
      {error ? <LoadError label="Couldn't load the table list" onRetry={reload} compact /> : !data ? <BootFallback variant="panel" /> : (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs text-sf-ink-dim">
              <th className="py-1.5 font-medium">Table</th>
              <th className="py-1.5 text-right font-medium">Columns</th>
              <th className="py-1.5 text-right font-medium">Rows (estimated)</th>
            </tr>
          </thead>
          <tbody>
            {data.tables.map(t => (
              <tr key={t.name} className="border-t border-sf-line">
                <td className="py-1.5 font-mono text-xs text-sf-ink" title={t.columns.join(', ')}>{t.name}</td>
                <td className="py-1.5 text-right text-sf-ink-mute">{t.columns.length}</td>
                <td className="py-1.5 text-right text-sf-ink-mute">{t.estimated_rows.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
