/**
 * /reports: the reports this user may run (the server filters by role), a params form generated
 * from the report's schema, the result as a table, and the same run as a CSV download.
 */
import { useState } from 'react';
import { useSearchParams } from 'react-router';
import { fetchJson } from '../api/client';
import { useJson } from '../api/useJson';
import { LoadError } from '../../shared/LoadError';
import { ReportParamsForm } from './ReportParamsForm';
import { initialParams, missingParams, paramsQuery, type ParamValues } from './reportParams';
import { ReportTable } from './ReportTable';
import type { ReportInfo, ReportResult } from './types';
import { BTN_PRIMARY, BTN_SECONDARY, H_PAGE, MUTED, PAGE, errorText } from './ui';

export default function ReportsPage() {
  const { data: reports, error, reload } = useJson<ReportInfo[]>('/api/core/reports');
  const [search, setSearch] = useSearchParams();
  const selected = reports?.find(r => r.key === search.get('report')) ?? reports?.[0] ?? null;

  return (
    <div className={PAGE}>
      <h1 className={`${H_PAGE} mb-6`}>Reports</h1>
      {error ? <LoadError label="Couldn't load the reports" onRetry={reload} />
        : !reports ? <p className={MUTED}>Loading…</p>
        : reports.length === 0 ? <p className={MUTED}>No reports are available to you yet.</p>
        : (
          <div className="flex flex-col gap-6 md:flex-row">
            <nav aria-label="Reports" className="flex shrink-0 gap-1 overflow-x-auto md:w-56 md:flex-col">
              {reports.map(r => (
                <button key={r.key} type="button" aria-current={r.key === selected?.key ? 'page' : undefined}
                  onClick={() => setSearch({ report: r.key })}
                  className={`cursor-pointer whitespace-nowrap rounded border-0 px-3 py-2 text-left font-sans text-sm md:whitespace-normal ${
                    r.key === selected?.key ? 'bg-sf-raised text-sf-ink' : 'bg-transparent text-sf-ink-soft hover:bg-sf-hover'}`}>
                  {r.label}
                </button>
              ))}
            </nav>
            {/* key: a fresh form and result for each report. */}
            {selected && <Report key={selected.key} report={selected} />}
          </div>
        )}
    </div>
  );
}

function Report({ report }: { report: ReportInfo }) {
  const [values, setValues] = useState<ParamValues>(() => initialParams(report.params));
  const [result, setResult] = useState<ReportResult | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const missing = missingParams(report.params, values);
  const query = paramsQuery(values);
  const path = `/api/core/reports/${encodeURIComponent(report.key)}`;

  async function run() {
    setRunning(true);
    setRunError(null);
    try {
      setResult(await fetchJson<ReportResult>(query ? `${path}?${query}` : path));
    } catch (err) {
      setResult(null);
      setRunError(errorText(err, "Couldn't run the report. Try again."));
    } finally {
      setRunning(false);
    }
  }

  return (
    <section aria-label={report.label} className="flex min-w-0 flex-1 flex-col gap-4">
      <div>
        <h2 className="m-0 font-display text-lg font-medium text-sf-ink">{report.label}</h2>
        <p className="m-0 text-xs text-sf-ink-dim">{report.app}{report.admin_only ? ' · admins only' : ''}</p>
      </div>
      <form className="flex flex-col gap-4" onSubmit={e => { e.preventDefault(); void run(); }}>
        <ReportParamsForm schema={report.params} values={values} onChange={setValues} />
        <div className="flex flex-wrap items-center gap-2">
          <button type="submit" className={BTN_PRIMARY} disabled={running || missing.length > 0}>{running ? 'Running…' : 'Run'}</button>
          {missing.length > 0
            ? <span className="text-xs text-sf-ink-dim">Fill in {missing.join(', ')}.</span>
            : <a href={`${path}/csv${query ? `?${query}` : ''}`} download className={`${BTN_SECONDARY} no-underline`}>Download CSV</a>}
        </div>
      </form>
      {runError && <p role="alert" className="m-0 text-sm text-sf-red-text">{runError}</p>}
      {result && <ReportTable result={result} />}
    </section>
  );
}
