import { pretty, type ToolPart } from './chatModel';
import { outcomeText, type ConfirmState, type Decision } from './confirmState';

const TONE: Record<string, string> = {
  pending: 'border-sf-amber/40 bg-sf-amber/8',
  done: 'border-sf-green/40 bg-sf-green/8',
  error: 'border-sf-red/40 bg-sf-red/8',
  uncertain: 'border-sf-amber/40 bg-sf-amber/8',
  stale: 'border-sf-amber/40 bg-sf-amber/8',
  denied: 'border-sf-line-strong bg-sf-raised',
  already_resolved: 'border-sf-line-strong bg-sf-raised',
};

const OUTCOME_TEXT_COLOR: Record<string, string> = {
  done: 'text-sf-green-text', error: 'text-sf-red-text', uncertain: 'text-sf-amber-text', stale: 'text-sf-amber-text',
  denied: 'text-sf-ink-soft', already_resolved: 'text-sf-ink-soft',
};

const TITLE: Record<string, string> = {
  done: 'Done', error: 'Failed', uncertain: 'Outcome unknown', stale: 'Not run: out of date',
  denied: 'Denied', already_resolved: 'Already handled',
};

/**
 * The approval card for a write Whisk proposed (`confirm` event, or a pending run in a saved
 * thread). Shows the full arguments; Approve and Deny go to POST /api/agent/confirm, and the
 * server's answer is what the card shows.
 */
export function ToolConfirmCard({ part, disabled, onDecide }: {
  part: ToolPart & { confirm: ConfirmState };
  disabled?: boolean;
  onDecide: (decision: Decision) => void;
}) {
  const state = part.confirm;
  const key = state.phase === 'resolved' ? state.outcome : 'pending';
  return (
    <div className={`rounded-md border border-solid p-3 ${TONE[key]}`} data-testid="tool-confirm-card">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className={`text-xs font-semibold uppercase tracking-wider ${state.phase === 'resolved' ? OUTCOME_TEXT_COLOR[key] : 'text-sf-amber-text'}`}>
          {state.phase === 'resolved' ? TITLE[key] : 'Needs your approval'}
        </span>
        <code className="break-all font-mono text-xs text-sf-ink-soft">{part.tool}</code>
      </div>
      {part.description && <p className="mb-0 mt-1.5 text-sm text-sf-ink">{part.description}</p>}
      <pre className="mb-0 mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-all rounded bg-sf-card p-2 font-mono text-xs text-sf-ink-mute">
        {pretty(part.args ?? {})}
      </pre>

      {state.phase !== 'resolved' && (
        <>
          {state.phase === 'pending' && state.failure && (
            <p role="alert" className="mb-0 mt-2 text-sm text-sf-red-text">{state.failure}</p>
          )}
          <div className="mt-3 flex gap-2">
            <button type="button" disabled={disabled || state.phase === 'sending'} onClick={() => onDecide('approve')}
              className="cursor-pointer rounded border-0 bg-sf-accent px-3.5 py-1.5 text-sm font-medium text-sf-accent-ink disabled:cursor-default disabled:opacity-60">
              {state.phase === 'sending' && state.decision === 'approve' ? 'Approving…' : 'Approve'}
            </button>
            <button type="button" disabled={disabled || state.phase === 'sending'} onClick={() => onDecide('deny')}
              className="cursor-pointer rounded border border-solid border-sf-line-strong bg-transparent px-3.5 py-1.5 text-sm text-sf-ink-mute disabled:cursor-default disabled:opacity-60">
              {state.phase === 'sending' && state.decision === 'deny' ? 'Denying…' : 'Deny'}
            </button>
          </div>
        </>
      )}

      {state.phase === 'resolved' && (
        <>
          <p className={`mb-0 mt-2 text-sm ${OUTCOME_TEXT_COLOR[key]}`}>{outcomeText(state)}</p>
          {state.outcome === 'done' && state.result !== undefined && (
            <details className="mt-2" open>
              <summary className="cursor-pointer text-xs text-sf-ink-dim">Result</summary>
              <pre className="mb-0 mt-1 max-h-56 overflow-auto whitespace-pre-wrap break-all rounded bg-sf-card p-2 font-mono text-xs text-sf-ink-mute">
                {pretty(state.result)}
              </pre>
            </details>
          )}
        </>
      )}
    </div>
  );
}
