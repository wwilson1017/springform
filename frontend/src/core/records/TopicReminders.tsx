/**
 * The user's topic reminders on /reminders: notes the assistant shows when a later message of theirs
 * mentions one of the terms (set by asking the assistant "when X comes up, remind me of Y"). Each can be
 * deleted; nothing else here edits them.
 */
import { useState } from 'react';
import { del } from '../api/client';
import { useJson } from '../api/useJson';
import { useAgentName } from '../agent/useAgentName';
import { confirmDialog } from '../../shared/confirm';
import { formatDate } from '../../shared/formatDate';
import { LoadError } from '../../shared/LoadError';
import { toast } from '../../shared/toast';
import type { TopicReminder } from './types';
import { BTN_DANGER_LINK, H_SECTION, MUTED, errorText } from './ui';

export const INTENTS = '/api/agent/intents';

const STATUS: Record<TopicReminder['status'], string> = {
  active: 'Active',
  used_up: 'Used up',
  expired: 'Expired',
};

export function TopicReminders() {
  const { data, error, reload } = useJson<TopicReminder[]>(INTENTS);
  const agent = useAgentName();
  const [busy, setBusy] = useState<number | null>(null);

  async function remove(t: TopicReminder) {
    if (
      !(await confirmDialog({
        title: 'Delete topic reminder',
        message: `Delete the reminder for "${t.terms.join('", "')}"?`,
        confirmLabel: 'Delete',
        danger: true,
      }))
    )
      return;
    setBusy(t.id);
    try {
      await del(`${INTENTS}/${t.id}`);
      reload();
    } catch (err) {
      toast.error(errorText(err, "Couldn't delete the topic reminder."));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="mt-10" aria-labelledby="topic-reminders">
      <h2 id="topic-reminders" className={H_SECTION}>
        Topic reminders
      </h2>
      <p className={`${MUTED} mb-3`}>
        Ask {agent} "when the supplier comes up, remind me to…" and it will bring the note up when you mention it.
      </p>
      {error ? (
        <LoadError label="Couldn't load your topic reminders" onRetry={reload} />
      ) : !data ? (
        <p className={MUTED}>Loading…</p>
      ) : data.length === 0 ? (
        <p className={MUTED}>No topic reminders yet.</p>
      ) : (
        <ul className="m-0 list-none divide-y divide-sf-line p-0">
          {data.map((t) => (
            <li key={t.id} className="flex flex-col gap-1 py-2.5">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className={`text-sm ${t.status === 'active' ? 'text-sf-ink' : 'text-sf-ink-soft line-through'}`}>
                  {t.terms.join(', ')}
                </span>
                <span className="text-xs text-sf-ink-dim">{STATUS[t.status]}</span>
              </div>
              <p className="m-0 text-xs text-sf-ink-mute">{t.note}</p>
              <div className="flex flex-wrap items-center gap-x-2 text-xs text-sf-ink-dim">
                <span>
                  Shown {t.fires} of {t.max_fires} times
                </span>
                <span>· until {formatDate(t.expires_at)}</span>
                <button
                  type="button"
                  className={`${BTN_DANGER_LINK} ml-2`}
                  disabled={busy === t.id}
                  aria-label={`Delete topic reminder ${t.terms.join(', ')}`}
                  onClick={() => void remove(t)}
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
