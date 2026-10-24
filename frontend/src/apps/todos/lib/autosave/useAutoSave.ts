import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError, apiErrorMessage } from '../../errors';
import type { AutoSave, AutoSaveStatus, SaveOutcome } from './types';

/**
 * The blur/field-commit auto-save lifecycle (#2032).
 *
 * The hook owns WHEN a save runs and what the user is told about it; the caller owns
 * WHAT is written. That split is the whole reason this is shareable: `performSave`
 * reads the caller's own draft, baseline and concurrency token at call time, so the
 * hook never learns a record shape.
 *
 * Two properties are load-bearing and easy to lose in a rewrite:
 *
 *   1. **Single-flight with one trailing run.** A `commit()` during a save does not
 *      issue a second request — it raises a flag, and the in-flight run re-fires once
 *      when it settles, recomputing the payload from the caller's refs at that moment.
 *      Concurrent writes would each carry their own optimistic-concurrency token and
 *      the second would 409 against the first — a conflict the user never caused.
 *   2. **`flush()` resolves on CHAIN settle, not on the current request.** A close
 *      guard awaits `flush()` and unmounts the surface on `true`; resolving while a
 *      trailing run is still queued would tear down the form with the user's last edit
 *      still unsent.
 *
 * There are no timers here. Blur-commit needs none, and `core/hooks/useDebounce` is
 * the repo's one debounce — this is not a second one.
 */
/**
 * What the status line is allowed to say about a failure: the server's sentence, never a bare
 * status text (a framework validation error's LIST of field problems arrives as one). The line
 * is persistent and a screen reader announces it, so anything else gets a human sentence.
 */
function readableError(err: unknown): string {
  if (!(err instanceof ApiError)) {
    return err instanceof Error ? err.message : 'Could not save.';
  }
  return apiErrorMessage(err, 'the server rejected those values.');
}

export function useAutoSave(
  /**
   * Write everything currently dirty in ONE call. Resolve `'nothing-to-save'` on an
   * empty diff; THROW on failure. Read every input from refs, not from a render
   * closure: the trailing run calls this again after the first save has already moved
   * the baseline forward.
   */
  performSave: () => Promise<SaveOutcome>,
  /** Pure read over the caller's refs: does the draft differ from the baseline? */
  isDirty: () => boolean,
): AutoSave {
  const [status, setStatus] = useState<AutoSaveStatus>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Held in refs and refreshed every render so a continuation always calls the LATEST
  // closure. This is what makes "recompute the payload at send time" true rather than
  // aspirational — a captured closure would re-send the first attempt's stale draft.
  const performSaveRef = useRef(performSave);
  const isDirtyRef = useRef(isDirty);
  useEffect(() => {
    performSaveRef.current = performSave;
    isDirtyRef.current = isDirty;
  });

  const statusRef = useRef<AutoSaveStatus>('idle');
  const queuedRef = useRef(false);
  // Bumped by `reset()` and on unmount. Every chain captures the generation it started
  // in and writes nothing once it is stale — the hook's own version of the panel's
  // `activeTaskId` guard, so a save resolving after the user moved to another record
  // neither reports a status nor fires a trailing run against the new one.
  const genRef = useRef(0);
  const chainRef = useRef<Promise<boolean> | null>(null);

  const setStatusSafely = useCallback((gen: number, next: AutoSaveStatus) => {
    if (gen !== genRef.current) return;
    statusRef.current = next;
    setStatus(next);
  }, []);

  useEffect(
    () => () => {
      genRef.current += 1;
    },
    [],
  );

  /** One request plus however many trailing re-runs the coalescing asks for. */
  const runChain = useCallback(
    async (gen: number): Promise<boolean> => {
      for (;;) {
        try {
          await performSaveRef.current();
        } catch (err) {
          // Gen first, exactly as the success path below: `queued` is shared across
          // generations, so a stale chain clearing it would swallow a LIVE generation's
          // trailing run. Within a live generation it is cleared on every exit, or a
          // later retry inherits a trailing run it never asked for.
          if (gen !== genRef.current) return false;
          queuedRef.current = false;
          const conflict = err instanceof ApiError && err.status === 409;
          setErrorMessage(readableError(err));
          setStatusSafely(gen, conflict ? 'conflict' : 'error');
          return false;
        }
        if (gen !== genRef.current) return false;

        // A commit that arrived mid-flight re-runs exactly once, and only if the
        // draft is still ahead of the baseline the finished save just moved.
        if (queuedRef.current && isDirtyRef.current()) {
          queuedRef.current = false;
          continue;
        }
        queuedRef.current = false;
        const stillDirty = isDirtyRef.current();
        setStatusSafely(gen, stillDirty ? 'dirty' : 'saved');
        return !stillDirty;
      }
    },
    [setStatusSafely],
  );

  /**
   * The one entry point. `commit()` is this without the promise; `flush()` is this
   * with it. Joining an in-flight chain returns that chain, so both callers wait for
   * the trailing run too.
   */
  const start = useCallback((): Promise<boolean> => {
    if (statusRef.current === 'conflict') return Promise.resolve(false);

    if (statusRef.current === 'saving') {
      queuedRef.current = true;
      return chainRef.current ?? Promise.resolve(false);
    }

    // `error` retries unconditionally: the draft may equal the baseline and still be
    // unsaved, because the write that would have moved the baseline is the one that failed.
    if (!isDirtyRef.current() && statusRef.current !== 'error') {
      if (statusRef.current === 'dirty') setStatusSafely(genRef.current, 'saved');
      return Promise.resolve(true);
    }

    const gen = genRef.current;
    setErrorMessage(null);
    setStatusSafely(gen, 'saving');
    const chain = runChain(gen).finally(() => {
      if (chainRef.current === chain) chainRef.current = null;
    });
    chainRef.current = chain;
    return chain;
  }, [runChain, setStatusSafely]);

  const commit = useCallback(() => {
    void start();
  }, [start]);

  const flush = useCallback(() => start(), [start]);

  const syncDirty = useCallback(() => {
    const current = statusRef.current;
    // `saving` settles itself; `conflict`/`error` are terminal until the user acts —
    // typing more must not quietly erase either message.
    if (current === 'saving' || current === 'conflict' || current === 'error') return;
    setStatusSafely(genRef.current, isDirtyRef.current() ? 'dirty' : current === 'dirty' ? 'saved' : current);
  }, [setStatusSafely]);

  const reset = useCallback(() => {
    genRef.current += 1;
    queuedRef.current = false;
    chainRef.current = null;
    statusRef.current = 'idle';
    setStatus('idle');
    setErrorMessage(null);
  }, []);

  return { status, errorMessage, commit, flush, syncDirty, reset };
}
