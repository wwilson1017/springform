import { useCallback, useEffect, useState } from 'react';
import { fetchJson } from './client';

/**
 * GET `url` and keep the result. `null` skips the request. Data from a previous `url` is never
 * returned for a new one. `reload()` refetches; `setData` applies a known update (a PATCH
 * response) without a round trip.
 */
export function useJson<T>(url: string | null) {
  const [state, setState] = useState<{ url: string | null; data: T | null; error: Error | null }>(
    { url: null, data: null, error: null },
  );
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!url) return;
    const ctrl = new AbortController();
    fetchJson<T>(url, ctrl.signal).then(
      data => setState({ url, data, error: null }),
      (error: Error) => { if (!ctrl.signal.aborted) setState({ url, data: null, error }); },
    );
    return () => ctrl.abort();
  }, [url, tick]);

  const reload = useCallback(() => setTick(t => t + 1), []);
  const setData = useCallback((data: T) => setState(s => ({ ...s, data, error: null })), []);
  const fresh = state.url === url;
  return { data: fresh ? state.data : null, error: fresh ? state.error : null, reload, setData };
}
