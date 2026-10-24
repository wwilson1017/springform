import { useState } from 'react';
import { ApiError, postJson } from '../api/client';
import { useJson } from '../api/useJson';
import BootFallback from '../components/BootFallback';
import { buttonClass, chipClass } from '../settings/ui';
import { formatDate } from '../../shared/formatDate';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { KeyPanel } from './KeyPanel';
import type { BackupRun, BackupsOverview } from './types';

/** `20261024T033507Z` → the same instant as an ISO string, for formatDate. */
const stampIso = (s: string) => `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}T${s.slice(9, 11)}:${s.slice(11, 13)}:${s.slice(13, 15)}Z`;

function formatBytes(n: number | null): string {
  if (n == null) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

const panelClass = 'rounded-lg border border-sf-line-strong bg-sf-card p-5';
const linkClass = 'text-sf-accent-text';

/** `/backups` (admin): the recovery sets, "Back up now", the last run and the encryption key. */
export default function BackupsPage() {
  const { data, error, reload } = useJson<BackupsOverview>('/api/core/backups');
  const [running, setRunning] = useState(false);

  async function backUpNow() {
    setRunning(true);
    try {
      const run = await postJson<BackupRun>('/api/core/backups/run');
      if (run.status === 'ok') toast.success('Backup written');
      else toast.error(run.status === 'skipped' ? `Backup skipped: ${run.error}` : `Backup failed: ${run.error}`);
      reload();
    } catch (e) {
      toast.error(e instanceof ApiError && e.status === 409 ? 'A backup is already running. Try again in a moment.' : "Couldn't start the backup.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5 px-4 py-8 md:px-8">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="m-0 flex-1 font-display text-2xl font-medium text-sf-ink">Backups</h1>
        <button type="button" onClick={() => void backUpNow()} disabled={running || !data} className={buttonClass}>
          {running ? 'Backing up…' : 'Back up now'}
        </button>
      </div>
      {error ? <LoadError label="Couldn't load backups" onRetry={reload} /> : !data ? <BootFallback variant="panel" /> : (
        <>
          <p className="m-0 text-sm text-sf-ink-mute">
            Each set is a snapshot of the database plus a manifest of the attachments it needs. The newest 7 are kept,
            and one is taken every night at 03:00. {data.last_backup_at ? `Last complete set: ${formatDate(data.last_backup_at)}.` : 'No complete set yet.'}
          </p>
          {data.last_run && <LastRun run={data.last_run} />}
          <section aria-labelledby="sets-heading" className={panelClass}>
            <h2 id="sets-heading" className="m-0 mb-3 font-display text-base font-medium text-sf-ink">Recovery sets</h2>
            {data.sets.length === 0 ? <p className="m-0 text-sm text-sf-ink-mute">No backups yet.</p> : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="text-left text-xs text-sf-ink-dim">
                      <th className="py-1.5 pr-3 font-medium">Taken</th>
                      <th className="py-1.5 pr-3 text-right font-medium">Size</th>
                      <th className="hidden py-1.5 pr-3 text-right font-medium md:table-cell">Files</th>
                      <th className="py-1.5 pr-3 font-medium">Status</th>
                      <th className="hidden py-1.5 font-medium md:table-cell"><span className="sr-only">Actions</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.sets.map(set => (
                      <tr key={set.stamp} className="border-t border-sf-line align-top">
                        <td className="py-2 pr-3">
                          <div className="text-sf-ink" title={set.created_at ?? undefined}>{formatDate(stampIso(set.stamp))}</div>
                          <div className="font-mono text-xs text-sf-ink-dim">{set.stamp}</div>
                          <div className="mt-1 text-sm md:hidden"><SetLinks stamp={set.stamp} /></div>
                        </td>
                        <td className="whitespace-nowrap py-2 pr-3 text-right text-sf-ink-mute">{formatBytes(set.snapshot_bytes)}</td>
                        <td className="hidden py-2 pr-3 text-right text-sf-ink-mute md:table-cell">{set.blob_count ?? '—'}</td>
                        <td className="py-2 pr-3">
                          <span className="flex flex-wrap gap-1">
                            {set.status && <span className={chipClass}>{set.status}</span>}
                            <span className={`${chipClass} ${set.manifest_ok ? 'text-sf-green-text' : 'text-sf-red-text'}`}>
                              {set.manifest_ok ? 'Complete' : 'Incomplete'}
                            </span>
                          </span>
                        </td>
                        <td className="hidden whitespace-nowrap py-2 text-right md:table-cell"><SetLinks stamp={set.stamp} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <section aria-labelledby="key-heading" className={panelClass}>
            <h2 id="key-heading" className="m-0 mb-3 font-display text-base font-medium text-sf-ink">Encryption key</h2>
            <KeyPanel keySource={data.key_source} keyShown={data.key_shown} />
          </section>
        </>
      )}
    </div>
  );
}

/** On narrow screens these sit under the stamp instead of in their own column. */
function SetLinks({ stamp }: { stamp: string }) {
  return (
    <>
      <a href={`/api/core/backups/${stamp}/download`} download className={linkClass}>Download</a>
      <a href={`/api/core/backups/${stamp}/manifest`} target="_blank" rel="noreferrer" className={`${linkClass} ml-3`}>Manifest</a>
    </>
  );
}

function LastRun({ run }: { run: BackupRun }) {
  const tone = run.status === 'ok' ? 'text-sf-green-text' : run.status === 'skipped' ? 'text-sf-amber-text' : 'text-sf-red-text';
  const label = { ok: 'Succeeded', skipped: 'Skipped', error: 'Failed' }[run.status];
  return (
    <section aria-label="Last run" className={panelClass}>
      <p className="m-0 text-sm text-sf-ink">
        Last run: <span className={`font-medium ${tone}`}>{label}</span>
        <span className="text-sf-ink-mute"> · {formatDate(run.started_at)}{run.byte_size != null && ` · ${formatBytes(run.byte_size)}`}</span>
      </p>
      {run.error && <p className={`mb-0 mt-2 break-words text-sm ${tone}`}>{run.status === 'skipped' ? 'Why: ' : 'Error: '}{run.error}</p>}
    </section>
  );
}
