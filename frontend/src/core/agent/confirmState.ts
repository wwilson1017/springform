/**
 * The approval card's state machine. The server is the authority (POST /api/agent/confirm is
 * idempotent and says what really happened), so the card only ever moves:
 *
 *   pending --decide--> sending --response--> resolved
 *                          \-----failed-----> pending (with the failure, so it can be retried)
 *
 * A second click while sending is ignored, and nothing leaves `resolved`.
 */

import type { ConfirmOutcome, ConfirmResponse, ToolStatus } from './types';

export type Decision = 'approve' | 'deny';

export type ConfirmState =
  | { phase: 'pending'; failure?: string }
  | { phase: 'sending'; decision: Decision }
  | { phase: 'resolved'; decision: Decision; outcome: ConfirmOutcome; result?: unknown; error?: string; current?: ToolStatus };

export type ConfirmEvent =
  | { type: 'decide'; decision: Decision }
  | { type: 'response'; body: ConfirmResponse }
  | { type: 'failed'; message: string };

const OUTCOMES: ConfirmOutcome[] = ['done', 'error', 'uncertain', 'stale', 'denied', 'already_resolved'];

export function confirmReducer(state: ConfirmState, event: ConfirmEvent): ConfirmState {
  switch (event.type) {
    case 'decide':
      return state.phase === 'pending' ? { phase: 'sending', decision: event.decision } : state;
    case 'failed':
      return state.phase === 'sending' ? { phase: 'pending', failure: event.message } : state;
    case 'response': {
      if (state.phase !== 'sending') return state;
      const { status, result, error, current } = event.body;
      // An answer this client does not know is shown as an error, never as success.
      const outcome = OUTCOMES.includes(status) ? status : 'error';
      return { phase: 'resolved', decision: state.decision, outcome, result, error, current };
    }
  }
}

/** The tool run's status once the card resolved, for the tool bubble beside it. */
export function runStatusOf(state: ConfirmState): ToolStatus {
  if (state.phase !== 'resolved') return 'pending';
  if (state.outcome === 'already_resolved') return state.current ?? 'done';
  return state.outcome;
}

/**
 * Resume the turn (POST /chat with only the conversation id) once every card of a message has
 * resolved, so the model hears every outcome at once, and only if this client resolved at
 * least one: `already_resolved` everywhere means another tab decided and resumed it.
 */
export function shouldResume(cards: ConfirmState[]): boolean {
  return cards.length > 0
    && cards.every(c => c.phase === 'resolved')
    && cards.some(c => c.phase === 'resolved' && c.outcome !== 'already_resolved');
}

/** The one-line explanation each outcome gets on the card. */
export function outcomeText(state: ConfirmState & { phase: 'resolved' }): string {
  switch (state.outcome) {
    case 'done': return 'Approved and done.';
    case 'denied': return 'Denied. Nothing was changed.';
    case 'error': return `Approved, but it failed${state.error ? `: ${state.error}` : '.'}`;
    case 'uncertain': return `It may or may not have happened${state.error ? ` (${state.error})` : ''}. Check before asking again.`;
    case 'stale': return 'This tool changed since it was proposed; ask again.';
    case 'already_resolved': return `Already handled${state.current ? ` (${state.current})` : ''}.`;
  }
}
