import { useState } from 'react';
import type { CardPart } from './chatModel';
import { outcomeText, type DecideOptions, type Decision } from './confirmState';
import { useAgentName } from './useAgentName';

/**
 * One Approve card for several same-shape calls of one step (the server's `batch` key): every
 * member's every value in a table, with Approve all and Deny all. Each pending member is still
 * confirmed on its own, in order (POST /api/agent/confirm per run), so a stale or failed one does
 * not stop the rest, and each row shows its own outcome.
 */
export function BatchConfirmCard({
  members,
  disabled,
  onDecide,
}: {
  members: CardPart[];
  disabled?: boolean;
  onDecide: (toolUseId: string, decision: Decision, opts?: DecideOptions) => Promise<void> | void;
}) {
  const agentName = useAgentName();
  const [reason, setReason] = useState('');
  const [alwaysAllow, setAlwaysAllow] = useState(false);
  const [busy, setBusy] = useState(false);
  const names = [...new Set(members.flatMap((m) => Object.keys(m.args ?? {})))].sort();
  const pending = members.filter((m) => m.confirm.phase === 'pending');
  const first = members[0];

  async function decideAll(decision: Decision) {
    setBusy(true);
    try {
      for (const m of pending)
        await onDecide(m.toolUseId, decision, decision === 'deny' ? { reason } : { alwaysAllow });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="rounded-md border border-solid border-sf-amber/40 bg-sf-amber/8 p-3"
      data-testid="batch-confirm-card"
    >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-xs font-semibold uppercase tracking-wider text-sf-amber-text">
          {pending.length ? 'Needs your approval' : 'Decided'} · {members.length} ×
        </span>
        <code className="break-all font-mono text-xs text-sf-ink-soft">{first.tool}</code>
      </div>
      {first.summary && <p className="mb-0 mt-1.5 text-sm text-sf-ink">{first.summary}</p>}
      <div className="mt-2 max-h-72 overflow-auto rounded bg-sf-card">
        <table className="w-full border-collapse font-mono text-xs text-sf-ink-mute">
          <thead>
            <tr>
              {names.map((n) => (
                <th key={n} className="px-2 py-1 text-left font-medium text-sf-ink-soft">
                  {n}
                </th>
              ))}
              <th className="px-2 py-1 text-left font-medium text-sf-ink-soft">status</th>
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.toolUseId} className="border-0 border-t border-solid border-sf-line">
                {names.map((n) => (
                  <td key={n} className="break-all px-2 py-1 align-top">
                    {/* JSON, so "1" and 1 read differently; never truncated */}
                    {JSON.stringify((m.args ?? {})[n])}
                  </td>
                ))}
                <td className="px-2 py-1 align-top font-sans">
                  {m.confirm.phase === 'resolved'
                    ? outcomeText(m.confirm)
                    : m.confirm.phase === 'sending'
                      ? 'Sending…'
                      : (m.confirm.failure ?? 'Waiting')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pending.length > 0 && (
        <>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              disabled={disabled || busy}
              onClick={() => void decideAll('approve')}
              className="cursor-pointer rounded border-0 bg-sf-accent px-3.5 py-1.5 text-sm font-medium text-sf-accent-ink disabled:cursor-default disabled:opacity-60"
            >
              Approve all {pending.length}
            </button>
            <button
              type="button"
              disabled={disabled || busy}
              onClick={() => void decideAll('deny')}
              className="cursor-pointer rounded border border-solid border-sf-line-strong bg-transparent px-3.5 py-1.5 text-sm text-sf-ink-mute disabled:cursor-default disabled:opacity-60"
            >
              Deny all
            </button>
          </div>
          <div className="mt-2 flex flex-col gap-2">
            <input
              type="text"
              maxLength={500}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              disabled={disabled || busy}
              aria-label="Reason for denying (optional)"
              placeholder="Reason for denying (optional)"
              className="w-full rounded border border-solid border-sf-line bg-sf-card px-2 py-1 text-sm text-sf-ink"
            />
            {members.every((m) => m.canAlwaysAllow) && (
              <label className="flex items-center gap-2 text-sm text-sf-ink-mute">
                <input
                  type="checkbox"
                  checked={alwaysAllow}
                  onChange={(e) => setAlwaysAllow(e.target.checked)}
                  disabled={disabled || busy}
                />
                Always allow <code className="font-mono text-xs">{first.tool}</code> in my chats with {agentName}
              </label>
            )}
          </div>
        </>
      )}
    </div>
  );
}
