import type { ReportResult } from './types';

function cell(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

/** A report's `{columns, rows}` as a table; wide ones scroll sideways inside the card. */
export function ReportTable({ result }: { result: ReportResult }) {
  if (result.rows.length === 0) return <p className="m-0 text-sm text-sf-ink-dim">No rows.</p>;
  return (
    <div className="overflow-x-auto rounded-md border border-sf-line">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="bg-sf-raised">
            {result.columns.map(c => <th key={c} scope="col" className="whitespace-nowrap px-3 py-2 text-left font-medium text-sf-ink-mute">{c.replace(/_/g, ' ')}</th>)}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, i) => (
            <tr key={i} className="border-t border-sf-line">
              {row.map((v, j) => <td key={j} className={`px-3 py-2 text-sf-ink ${typeof v === 'number' ? 'text-right tabular-nums' : ''}`}>{cell(v)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
