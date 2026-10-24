import { useState, useEffect } from 'react';

/**
 * The one debounce hook.
 *
 * `delay = 0` still round-trips through `setTimeout` + `useState` + an effect, so it is NOT a
 * synchronous escape hatch. A caller that needs the value on the same tick must branch before
 * the hook rather than passing 0.
 */
export function useDebounce<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}
