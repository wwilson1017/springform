import { useEffect, useState, type ReactNode } from 'react';
import { formatDate } from '../../shared/formatDate';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { ApiError, postJson } from '../api/client';
import { useJson } from '../api/useJson';
import { formatSeconds } from './format';
import { Chip, inputClass, Page, quietButtonClass } from './Page';
import type { DeadOutboxRow, JobInfo, JobRun, RunStatus } from './types';

const TONE: Record<RunStatus, 'green' | 'red' | 'amber' | 'plain'> = {
  ok: 'green', error: 'red', timed_out: 'red', running: 'amber', interrupted: 'plain', skipped: 'plain',
};
const StatusChip = ({ status }: { status: RunStatus }) => <Chip tone={TONE[status] ?? 'plain'}>{status.replace('_', ' ')}</Chip>;

function took(run: { started_at: string; finished_at: string | null }): string {
  if (!run.finished_at) return '';
  return formatSeconds((Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000);
}

/** Tell the admin why "Run now" was refused. */
function toastRefusal(name: string, e: unknown) {
  const detail = e instanceof ApiError ? e.detail : '';
  if (detail === 'already_running') toast.info(`${name} is already running; it was not started again.`);
  else if (detail === 'scheduler_not_running') toast.error("The scheduler isn't running on this server, so jobs can't be started now.");
  else if (detail === 'unknown_job') toast.error(`${name} isn't a job on this server any more.`);
  else toast.error(`Couldn't start ${name}.`);
}

export function JobsPage() {
  const { data: jobs, error: jobsError, reload: reloadJobs } = useJson<JobInfo[]>('/api/core/jobs');
  const [runsJob, setRunsJob] = useState('');
  const [runsLimit, setRunsLimit] = useState(20);
  const runsQuery = new URLSearchParams(runsJob ? { job: runsJob, limit: String(runsLimit) } : { limit: String(runsLimit) });
  const { data: runs, error: runsError, reload: reloadRuns } = useJson<JobRun[]>(`/api/core/jobs/runs?${runsQuery}`);
  const dead = useJson<DeadOutboxRow[]>('/api/core/jobs/outbox/dead?limit=50');
  const [starting, setStarting] = useState<string | null>(null);

  // While anything is in flight, re-read every few seconds so its finish shows without a reload.
  const inFlight = jobs?.some(j => j.in_flight) ?? false;
  useEffect(() => {
    if (!inFlight) return;
    const t = setInterval(() => { reloadJobs(); reloadRuns(); }, 3000);
    return () => clearInterval(t);
  }, [inFlight, reloadJobs, reloadRuns]);

  async function runNow(name: string) {
    setStarting(name);
    try {
      await postJson(`/api/core/jobs/${encodeURIComponent(name)}/run`);
      toast.success(`Started ${name}.`);
      // The run row appears once the scheduler picks the job up.
      setTimeout(() => { reloadJobs(); reloadRuns(); }, 1000);
    } catch (e) {
      toastRefusal(name, e);
    } finally {
      setStarting(null);
    }
  }

  return (
    <Page title="Jobs" intro="Scheduled work this install runs on its own. Times are in your browser's timezone; daily jobs run at the install's.">
      <section aria-labelledby="jobs-h" className="mb-10">
        <h2 id="jobs-h" className="sr-only">Jobs</h2>
        {jobsError ? <LoadError label="Couldn't load jobs" onRetry={reloadJobs} />
          : !jobs ? <p className="text-sm text-sf-ink-dim">Loading…</p>
          : (
            <ul className="m-0 list-none divide-y divide-sf-line rounded-lg border border-sf-line-strong bg-sf-card p-0">
              <li aria-hidden className="hidden gap-4 px-4 py-2 text-xs text-sf-ink-dim md:grid md:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)_minmax(0,1.6fr)_6.5rem]">
                <span>Job</span><span>Schedule</span><span>Last run</span><span />
              </li>
              {jobs.map(j => (
                <li key={j.name} className="grid gap-x-4 gap-y-1 px-4 py-3 md:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)_minmax(0,1.6fr)_6.5rem] md:items-center">
                  <div className="flex min-w-0 items-center gap-2">
                    <span title={j.in_flight ? 'Running now' : undefined}
                      className={`h-2 w-2 shrink-0 rounded-full ${j.in_flight ? 'animate-pulse bg-sf-amber' : 'bg-transparent'}`} />
                    {j.in_flight && <span className="sr-only">Running now:</span>}
                    <button type="button" title="Show this job's runs" onClick={() => setRunsJob(j.name)}
                      className="min-w-0 cursor-pointer truncate border-0 bg-transparent p-0 text-left font-sans text-sm text-sf-ink hover:underline">
                      {j.name}
                    </button>
                    {j.app !== 'core' && <Chip>{j.app}</Chip>}
                  </div>
                  <div className="text-sm text-sf-ink-mute">
                    {j.every != null ? `Every ${formatSeconds(j.every)}` : `Daily at ${j.at}`}
                    <span className="block text-xs text-sf-ink-dim">Timeout {formatSeconds(j.timeout)}</span>
                  </div>
                  <div className="min-w-0 text-sm text-sf-ink-mute">
                    {j.last_run ? (
                      <>
                        <StatusChip status={j.last_run.status} />{' '}
                        <span className="text-xs">{formatDate(j.last_run.started_at)}</span>
                        {j.last_run.error && <div className="mt-1 text-xs break-words text-sf-red-text">{j.last_run.error}</div>}
                      </>
                    ) : <span className="text-xs text-sf-ink-dim">Never run</span>}
                  </div>
                  <div className="md:text-right">
                    <button type="button" onClick={() => void runNow(j.name)} disabled={starting === j.name} className={quietButtonClass}>
                      Run now
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
      </section>

      <section aria-labelledby="runs-h" className="mb-10">
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <h2 id="runs-h" className="m-0 flex-1 font-display text-base font-medium text-sf-ink">Runs</h2>
          <label className="flex items-center gap-2 text-xs text-sf-ink-dim">
            Job
            <select value={runsJob} onChange={e => setRunsJob(e.target.value)} className={inputClass}>
              <option value="">All jobs</option>
              {(jobs ?? []).map(j => <option key={j.name} value={j.name}>{j.name}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-sf-ink-dim">
            Show
            <select value={runsLimit} onChange={e => setRunsLimit(Number(e.target.value))} className={inputClass}>
              {[20, 50, 200].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        </div>
        {runsError ? <LoadError label="Couldn't load runs" onRetry={reloadRuns} />
          : !runs ? <p className="text-sm text-sf-ink-dim">Loading…</p>
          : runs.length === 0 ? <p className="text-sm text-sf-ink-dim">No runs yet.</p>
          : (
            <Table head={['Started', 'Job', 'Trigger', 'Status', 'Took', 'Error']}>
              {runs.map(r => (
                <tr key={r.id}>
                  <Td>{formatDate(r.started_at)}</Td>
                  <Td>{r.job}{r.scheduled_for && <span className="block text-xs text-sf-ink-dim">for {r.scheduled_for}</span>}</Td>
                  <Td>{r.trigger}</Td>
                  <Td><StatusChip status={r.status} /></Td>
                  <Td>{took(r)}</Td>
                  <Td wrap>{r.error}</Td>
                </tr>
              ))}
            </Table>
          )}
      </section>

      <section aria-labelledby="dead-h">
        <h2 id="dead-h" className="m-0 mb-1 font-display text-base font-medium text-sf-ink">Dead outbox</h2>
        <p className="mt-0 mb-3 text-sm text-sf-ink-soft">Follow-up work (hooks) that kept failing and was given up on.</p>
        {dead.error ? <LoadError label="Couldn't load the dead outbox" onRetry={dead.reload} />
          : !dead.data ? <p className="text-sm text-sf-ink-dim">Loading…</p>
          : dead.data.length === 0 ? <p className="text-sm text-sf-ink-dim">Nothing here.</p>
          : (
            <Table head={['Id', 'Hook', 'Attempts', 'Last error', 'Created', 'Gave up']}>
              {dead.data.map(d => (
                <tr key={d.id}>
                  <Td>{d.id}</Td>
                  <Td>{d.hook}</Td>
                  <Td>{d.attempts}</Td>
                  <Td wrap>{d.last_error}</Td>
                  <Td>{formatDate(d.created_at)}</Td>
                  <Td>{formatDate(d.dead_at)}</Td>
                </tr>
              ))}
            </Table>
          )}
      </section>
    </Page>
  );
}

function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-sf-line-strong bg-sf-card">
      <table className="w-full min-w-[40rem] border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-sf-line text-xs text-sf-ink-dim">
            {head.map(h => <th key={h} className="px-3 py-2 font-normal">{h}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-sf-line">{children}</tbody>
      </table>
    </div>
  );
}

function Td({ children, wrap }: { children: ReactNode; wrap?: boolean }) {
  return (
    <td className={`px-3 py-2 align-top text-sf-ink-mute ${wrap ? 'max-w-80 break-words text-xs text-sf-red-text' : 'whitespace-nowrap'}`}>
      {children}
    </td>
  );
}
