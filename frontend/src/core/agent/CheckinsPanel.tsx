/**
 * `/whisk/checkins`: the caller's scheduled check-ins (GET /api/agent/checkins). Create one (name,
 * prompt, every N minutes / daily / weekly at a time), pause or resume it (PATCH), run it now (POST
 * …/run) or delete it. A run's reply arrives as a notification; a run with nothing to report sends
 * nothing.
 */

import { useState, type FormEvent } from 'react';
import { del, patchJson, postJson } from '../api/client';
import { useJson } from '../api/useJson';
import { confirmDialog } from '../../shared/confirm';
import { formatDate } from '../../shared/formatDate';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import { btnPrimary, btnSecondary, errorText, inputSm, labelSm, noteText } from '../auth/api';
import { DAY_NAMES, DAYS, describeSchedule, scheduleText, type Kind } from './checkinSchedule';
import type { Checkin } from './types';

function lastResult(c: Checkin): string | null {
  if (!c.last_run_at) return null;
  if (c.last_status === 'ok') return `Delivered ${formatDate(c.last_run_at)}`;
  if (c.last_status === 'silent') return `Nothing to report ${formatDate(c.last_run_at)}`;
  const error = c.last_error ?? 'unknown error';
  // A resume clears the count but keeps the last error.
  return c.failures > 0 ? `Failed ${c.failures} in a row: ${error}` : `Last run failed: ${error}`;
}

export default function CheckinsPanel({ configured, agentName }: { configured: boolean; agentName: string }) {
  const list = useJson<Checkin[]>('/api/agent/checkins');
  const [busy, setBusy] = useState<number | 'new' | null>(null);
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [kind, setKind] = useState<Kind>('daily');
  const [minutes, setMinutes] = useState(60);
  const [day, setDay] = useState<string>('mon');
  const [time, setTime] = useState('09:00');

  async function act(id: number | 'new', fn: () => Promise<unknown>, ok: string, fail: string) {
    setBusy(id);
    try {
      await fn();
      toast.success(ok);
      list.reload();
      return true;
    } catch (e) {
      toast.error(errorText(e, {}, fail));
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    const body = { name, prompt, schedule: scheduleText(kind, minutes, day, time) };
    if (await act('new', () => postJson('/api/agent/checkins', body), 'Check-in saved.', "Couldn't save it.")) {
      setName('');
      setPrompt('');
    }
  }

  async function remove(c: Checkin) {
    const ok = await confirmDialog({
      title: 'Delete check-in',
      message: `"${c.name}" will stop running. This cannot be undone.`,
      confirmLabel: 'Delete',
      danger: true,
    });
    if (ok) await act(c.id, () => del(`/api/agent/checkins/${c.id}`), 'Check-in deleted.', "Couldn't delete it.");
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-6">
      <p className={noteText}>
        A check-in is a question {agentName} asks on a schedule, as you, with look-up tools only: it can read but never
        change anything. Its answer arrives as a notification; when there is nothing to report it stays quiet.
        {!configured && ' Check-ins wait until an AI key is added.'}
      </p>

      <form onSubmit={(e) => void create(e)} className="flex flex-col gap-3">
        <div>
          <label htmlFor="checkin-name" className={labelSm}>
            Name
          </label>
          <input
            id="checkin-name"
            className={inputSm}
            maxLength={80}
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="checkin-prompt" className={labelSm}>
            What to check
          </label>
          <textarea
            id="checkin-prompt"
            className={inputSm}
            rows={3}
            maxLength={4000}
            required
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor="checkin-kind" className={labelSm}>
              When
            </label>
            <select
              id="checkin-kind"
              className={inputSm}
              value={kind}
              onChange={(e) => setKind(e.target.value as Kind)}
            >
              <option value="every">Every few minutes</option>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
            </select>
          </div>
          {kind === 'every' && (
            <div>
              <label htmlFor="checkin-minutes" className={labelSm}>
                Minutes
              </label>
              <input
                id="checkin-minutes"
                type="number"
                className={inputSm}
                min={15}
                max={10080}
                value={minutes}
                onChange={(e) => setMinutes(Number(e.target.value))}
              />
            </div>
          )}
          {kind === 'weekly' && (
            <div>
              <label htmlFor="checkin-day" className={labelSm}>
                Day
              </label>
              <select id="checkin-day" className={inputSm} value={day} onChange={(e) => setDay(e.target.value)}>
                {DAYS.map((d, i) => (
                  <option key={d} value={d}>
                    {DAY_NAMES[i]}
                  </option>
                ))}
              </select>
            </div>
          )}
          {kind !== 'every' && (
            <div>
              <label htmlFor="checkin-time" className={labelSm}>
                Time
              </label>
              <input
                id="checkin-time"
                type="time"
                className={inputSm}
                required
                value={time}
                onChange={(e) => setTime(e.target.value)}
              />
            </div>
          )}
          <button type="submit" className={btnPrimary} disabled={busy === 'new'}>
            Add check-in
          </button>
        </div>
      </form>

      {list.error ? (
        <LoadError label="Couldn't load your check-ins" onRetry={list.reload} compact />
      ) : !list.data ? (
        <p className={noteText}>Loading…</p>
      ) : list.data.length === 0 ? (
        <p className={noteText}>No check-ins yet.</p>
      ) : (
        <ul className="m-0 list-none divide-y divide-sf-line p-0">
          {list.data.map((c) => (
            <li key={c.id} className="flex flex-col gap-2 py-3 text-sm">
              <div className="min-w-0">
                <div className="font-medium text-sf-ink">{c.name}</div>
                <div className="text-xs text-sf-ink-dim">
                  {describeSchedule(c.schedule)} · {c.enabled ? `Next run ${formatDate(c.next_run_at)}` : 'Paused'}
                </div>
                {lastResult(c) && <div className="text-xs text-sf-ink-soft">{lastResult(c)}</div>}
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className={btnSecondary}
                  disabled={!c.enabled || busy === c.id}
                  onClick={() =>
                    void act(
                      c.id,
                      () => postJson(`/api/agent/checkins/${c.id}/run`),
                      'Running now. A reply arrives as a notification.',
                      "Couldn't start it.",
                    )
                  }
                >
                  Run now
                </button>
                <button
                  type="button"
                  className={btnSecondary}
                  disabled={busy === c.id}
                  onClick={() =>
                    void act(
                      c.id,
                      () => patchJson(`/api/agent/checkins/${c.id}`, { enabled: !c.enabled }),
                      c.enabled ? 'Check-in paused.' : 'Check-in resumed.',
                      "Couldn't change it.",
                    )
                  }
                >
                  {c.enabled ? 'Pause' : 'Resume'}
                </button>
                <button type="button" className={btnSecondary} disabled={busy === c.id} onClick={() => void remove(c)}>
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
