// @vitest-environment jsdom
//
// The auto-save lifecycle (#2032). Every property pinned here is invisible to `tsc` and to
// eslint, and each one has a user-visible failure mode: a lost trailing save drops the last
// thing typed, a `flush()` that resolves early lets the close guard tear the panel down
// mid-write, a leaked queue flag fires a phantom second save, and a chain that survives
// `reset()` reports one task's status on another's panel.
//
// The harness is `createRoot` + React 19's `act`, per `core/hooks/useDebounce.test.tsx`.
import { act, useEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';

import { ApiError } from '../../errors';
import { useAutoSave } from './useAutoSave';
import type { AutoSave, SaveOutcome } from './types';

function renderHook<P, R>(useHook: (props: P) => R, initialProps: P) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const result: { current: R } = { current: undefined as unknown as R };
  function Probe({ value }: { value: P }) {
    const hookValue = useHook(value);
    useEffect(() => {
      result.current = hookValue;
    });
    return null;
  }
  let root!: Root;
  act(() => {
    root = createRoot(container);
    root.render(<Probe value={initialProps} />);
  });
  return {
    result,
    rerender: (props: P) => act(() => root.render(<Probe value={props} />)),
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

/** A save whose resolution the test controls, so "in flight" is a real state. */
function deferred() {
  let resolve!: (v: SaveOutcome) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<SaveOutcome>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

type Props = { performSave: () => Promise<SaveOutcome>; isDirty: () => boolean };
const mount = (props: Props) =>
  renderHook<Props, AutoSave>((p) => useAutoSave(p.performSave, p.isDirty), props);

describe('useAutoSave', () => {
  it('does not write when the draft matches the baseline', async () => {
    const performSave = vi.fn(async (): Promise<SaveOutcome> => 'saved');
    const hook = mount({ performSave, isDirty: () => false });

    await act(async () => {
      await hook.result.current.flush();
    });

    expect(performSave).not.toHaveBeenCalled();
    expect(hook.result.current.status).toBe('idle');
    hook.unmount();
  });

  it('saves a dirty draft and lands on saved', async () => {
    let dirty = true;
    const performSave = vi.fn(async (): Promise<SaveOutcome> => {
      dirty = false;
      return 'saved';
    });
    const hook = mount({ performSave, isDirty: () => dirty });

    await act(async () => {
      await hook.result.current.flush();
    });

    expect(performSave).toHaveBeenCalledTimes(1);
    expect(hook.result.current.status).toBe('saved');
    hook.unmount();
  });

  it('coalesces commits made during a save into ONE trailing run', async () => {
    const first = deferred();
    const performSave = vi.fn(() => first.promise);
    const hook = mount({ performSave, isDirty: () => true });

    act(() => hook.result.current.commit());
    expect(hook.result.current.status).toBe('saving');

    // Three more fields blur while the first write is still open.
    act(() => {
      hook.result.current.commit();
      hook.result.current.commit();
      hook.result.current.commit();
    });
    expect(performSave).toHaveBeenCalledTimes(1);

    const second = deferred();
    performSave.mockImplementation(() => second.promise);
    await act(async () => {
      first.resolve('saved');
      await first.promise;
    });
    // Exactly one re-run, not three — concurrent writes would each carry their own
    // concurrency token and the later ones would 409 against the earlier.
    expect(performSave).toHaveBeenCalledTimes(2);

    await act(async () => {
      second.resolve('saved');
      await second.promise;
    });
    hook.unmount();
  });

  it('skips the trailing run when the finished save already covered it', async () => {
    let dirty = true;
    const first = deferred();
    const performSave = vi.fn(() => first.promise);
    const hook = mount({ performSave, isDirty: () => dirty });

    act(() => hook.result.current.commit());
    act(() => hook.result.current.commit());

    dirty = false; // the in-flight write carried the queued change too
    await act(async () => {
      first.resolve('saved');
      await first.promise;
    });

    expect(performSave).toHaveBeenCalledTimes(1);
    expect(hook.result.current.status).toBe('saved');
    hook.unmount();
  });

  it('flush() joined mid-flight waits for the trailing run, not the current one', async () => {
    const first = deferred();
    const second = deferred();
    const performSave = vi.fn(() => first.promise);
    const hook = mount({ performSave, isDirty: () => true });

    act(() => hook.result.current.commit());

    let settled = false;
    let flushed: Promise<boolean>;
    act(() => {
      flushed = hook.result.current.flush();
      void flushed.then(() => {
        settled = true;
      });
    });

    performSave.mockImplementation(() => second.promise);
    await act(async () => {
      first.resolve('saved');
      await first.promise;
    });
    // The first write is done but the queued one is not — resolving here is what would let
    // a close guard unmount the panel with the user's last edit still unsent.
    expect(settled).toBe(false);
    expect(performSave).toHaveBeenCalledTimes(2);

    await act(async () => {
      second.resolve('saved');
      await second.promise;
    });
    expect(settled).toBe(true);
    hook.unmount();
  });

  it('classifies a 409 as a conflict and refuses further commits until reset', async () => {
    const performSave = vi.fn(async (): Promise<SaveOutcome> => {
      throw new ApiError(409, 'This task changed since you opened it.');
    });
    const hook = mount({ performSave, isDirty: () => true });

    let flushResult: boolean | undefined;
    await act(async () => {
      flushResult = await hook.result.current.flush();
    });

    expect(flushResult).toBe(false);
    expect(hook.result.current.status).toBe('conflict');
    expect(hook.result.current.errorMessage).toBe('This task changed since you opened it.');

    act(() => hook.result.current.commit());
    expect(performSave).toHaveBeenCalledTimes(1);

    act(() => hook.result.current.reset());
    expect(hook.result.current.status).toBe('idle');
    expect(hook.result.current.errorMessage).toBeNull();
    hook.unmount();
  });

  it('treats a non-409 failure as retryable and retries exactly once', async () => {
    let fail = true;
    const performSave = vi.fn(async (): Promise<SaveOutcome> => {
      if (fail) throw new ApiError(500, 'Could not reach the server.');
      return 'saved';
    });
    let dirty = true;
    const hook = mount({ performSave, isDirty: () => dirty });

    await act(async () => {
      await hook.result.current.flush();
    });
    expect(hook.result.current.status).toBe('error');
    // The server's own sentence, not `API error 500: …` — this string is read aloud.
    expect(hook.result.current.errorMessage).toBe('Could not reach the server.');

    // A commit that arrived while the doomed save was open must not survive it as a
    // queued run — the retry below would then fire twice.
    fail = false;
    dirty = false;
    await act(async () => {
      await hook.result.current.flush();
    });
    expect(performSave).toHaveBeenCalledTimes(2);
    expect(hook.result.current.status).toBe('saved');
    hook.unmount();
  });

  it('does not leak a queued run across a failure', async () => {
    const first = deferred();
    const performSave = vi.fn(() => first.promise);
    // The draft stays dirty THROUGHOUT, deliberately. A test that cleans it before the
    // retry passes whether or not the failure path clears `queued`, because the trailing
    // run is gated on `queued && isDirty()` — the dirty half alone would suppress it and
    // the assertion would prove nothing. Dirty-throughout means a leaked flag shows up as
    // a third call.
    const hook = mount({ performSave, isDirty: () => true });

    act(() => hook.result.current.commit());
    act(() => hook.result.current.commit()); // queued behind the doomed write

    await act(async () => {
      first.reject(new ApiError(500, 'boom'));
      await first.promise.catch(() => undefined);
    });
    expect(hook.result.current.status).toBe('error');
    expect(performSave).toHaveBeenCalledTimes(1);

    performSave.mockImplementation(async () => 'saved');
    await act(async () => {
      await hook.result.current.flush();
    });
    expect(performSave).toHaveBeenCalledTimes(2);
    hook.unmount();
  });

  it('abandons an in-flight chain on reset', async () => {
    const first = deferred();
    const performSave = vi.fn(() => first.promise);
    const hook = mount({ performSave, isDirty: () => true });

    act(() => hook.result.current.commit());
    act(() => hook.result.current.commit()); // would be the trailing run
    act(() => hook.result.current.reset());

    await act(async () => {
      first.resolve('saved');
      await first.promise;
    });

    // The panel moved to another task: the stale save neither reports a status nor fires
    // its trailing run against the record that replaced it.
    expect(performSave).toHaveBeenCalledTimes(1);
    expect(hook.result.current.status).toBe('idle');
    hook.unmount();
  });

  it('runs the LATEST performSave, so the trailing payload is recomputed', async () => {
    const first = deferred();
    const original = vi.fn(() => first.promise);
    const hook = mount({ performSave: original, isDirty: () => true });

    act(() => hook.result.current.commit());
    act(() => hook.result.current.commit());

    const second = deferred();
    const replacement = vi.fn(() => second.promise);
    hook.rerender({ performSave: replacement, isDirty: () => true });

    await act(async () => {
      first.resolve('saved');
      await first.promise;
    });

    expect(replacement).toHaveBeenCalledTimes(1);
    expect(original).toHaveBeenCalledTimes(1);

    await act(async () => {
      second.resolve('saved');
      await second.promise;
    });
    hook.unmount();
  });

  it('never announces a raw validation payload', async () => {
    // A framework 422 answers with a LIST of field problems, which the core client replaces
    // with the bare status text. The status line is persistent and screen-reader-announced, so
    // it gets a sentence instead of either.
    const performSave = vi.fn(async (): Promise<SaveOutcome> => {
      throw new ApiError(422, 'Unprocessable Entity');
    });
    const hook = mount({ performSave, isDirty: () => true });

    await act(async () => {
      await hook.result.current.flush();
    });

    expect(hook.result.current.status).toBe('error');
    expect(hook.result.current.errorMessage).toBe('the server rejected those values.');
    expect(hook.result.current.errorMessage).not.toContain('loc');
    hook.unmount();
  });

  it('syncDirty reports the draft without writing', async () => {
    let dirty = false;
    const performSave = vi.fn(async (): Promise<SaveOutcome> => 'saved');
    const hook = mount({ performSave, isDirty: () => dirty });

    dirty = true;
    act(() => hook.result.current.syncDirty());
    expect(hook.result.current.status).toBe('dirty');

    dirty = false;
    act(() => hook.result.current.syncDirty());
    expect(hook.result.current.status).toBe('saved');
    expect(performSave).not.toHaveBeenCalled();
    hook.unmount();
  });

  it('syncDirty never clears a conflict the user still has to resolve', async () => {
    const performSave = vi.fn(async (): Promise<SaveOutcome> => {
      throw new ApiError(409, 'stale');
    });
    const hook = mount({ performSave, isDirty: () => true });

    await act(async () => {
      await hook.result.current.flush();
    });
    act(() => hook.result.current.syncDirty());

    expect(hook.result.current.status).toBe('conflict');
    hook.unmount();
  });
});
