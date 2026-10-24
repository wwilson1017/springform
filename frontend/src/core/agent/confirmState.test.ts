import { describe, expect, it } from 'vitest';
import { confirmReducer, outcomeText, runStatusOf, shouldResume, type ConfirmState } from './confirmState';
import type { ConfirmResponse } from './types';

const pending: ConfirmState = { phase: 'pending' };
const sent = (decision: 'approve' | 'deny' = 'approve') => confirmReducer(pending, { type: 'decide', decision });
const answer = (body: ConfirmResponse, decision: 'approve' | 'deny' = 'approve') =>
  confirmReducer(sent(decision), { type: 'response', body });

describe('confirmReducer', () => {
  it('goes pending, sending, resolved with what the server said', () => {
    expect(sent()).toEqual({ phase: 'sending', decision: 'approve' });
    expect(answer({ status: 'done', result: { id: 3 } })).toEqual({
      phase: 'resolved', decision: 'approve', outcome: 'done', result: { id: 3 }, error: undefined, current: undefined,
    });
  });

  it('ignores a second decision while one is in flight, and anything after it resolved', () => {
    const sending = sent('approve');
    expect(confirmReducer(sending, { type: 'decide', decision: 'deny' })).toBe(sending);
    const resolved = answer({ status: 'denied' }, 'deny');
    expect(confirmReducer(resolved, { type: 'decide', decision: 'approve' })).toBe(resolved);
    expect(confirmReducer(resolved, { type: 'failed', message: 'x' })).toBe(resolved);
    expect(confirmReducer(resolved, { type: 'response', body: { status: 'done' } })).toBe(resolved);
  });

  it('a failed request goes back to pending with the reason, so it can be retried', () => {
    const failed = confirmReducer(sent(), { type: 'failed', message: 'Could not reach the server.' });
    expect(failed).toEqual({ phase: 'pending', failure: 'Could not reach the server.' });
    expect(confirmReducer(failed, { type: 'decide', decision: 'approve' }).phase).toBe('sending');
  });

  it('ignores a response that arrives when nothing was sent', () => {
    expect(confirmReducer(pending, { type: 'response', body: { status: 'done' } })).toBe(pending);
  });

  it('shows an unknown status as an error, never as success', () => {
    const r = answer({ status: 'exploded' as ConfirmResponse['status'] });
    expect(r.phase === 'resolved' && r.outcome).toBe('error');
  });

  it('gives every outcome its own words; stale says to ask again', () => {
    const outcomes: ConfirmResponse[] = [
      { status: 'done' }, { status: 'denied' }, { status: 'error', error: 'boom' }, { status: 'uncertain', error: 'timeout' },
      { status: 'stale' }, { status: 'already_resolved', current: 'done' },
    ];
    const texts = outcomes.map(body => {
      const s = answer(body);
      if (s.phase !== 'resolved') throw new Error('not resolved');
      return outcomeText(s);
    });
    expect(new Set(texts).size).toBe(outcomes.length);
    expect(texts[2]).toContain('boom');
    expect(texts[4]).toBe('This tool changed since it was proposed; ask again.');
  });
});

describe('runStatusOf', () => {
  it('maps the outcome to the run status, already_resolved to the current one', () => {
    expect(runStatusOf(pending)).toBe('pending');
    expect(runStatusOf(sent())).toBe('pending');
    expect(runStatusOf(answer({ status: 'stale' }))).toBe('stale');
    expect(runStatusOf(answer({ status: 'already_resolved', current: 'denied' }))).toBe('denied');
  });
});

describe('shouldResume', () => {
  it('waits for every card of the message', () => {
    expect(shouldResume([answer({ status: 'done' }), pending])).toBe(false);
    expect(shouldResume([answer({ status: 'done' }), sent()])).toBe(false);
    expect(shouldResume([answer({ status: 'done' }), answer({ status: 'denied' }, 'deny')])).toBe(true);
  });

  it('resumes after a deny or a failure too, so the model hears the outcome', () => {
    expect(shouldResume([answer({ status: 'denied' }, 'deny')])).toBe(true);
    expect(shouldResume([answer({ status: 'error', error: 'x' })])).toBe(true);
  });

  it('does not resume when another tab resolved everything, or there are no cards', () => {
    expect(shouldResume([answer({ status: 'already_resolved', current: 'done' })])).toBe(false);
    expect(shouldResume([])).toBe(false);
  });
});
