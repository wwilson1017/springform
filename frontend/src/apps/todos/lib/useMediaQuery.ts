import { useSyncExternalStore } from 'react';

/** Live result of a media query; false where there is no matchMedia (a unit test). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    onChange => {
      const mq = window.matchMedia?.(query);
      if (!mq) return () => {};
      mq.addEventListener('change', onChange);
      return () => mq.removeEventListener('change', onChange);
    },
    () => window.matchMedia?.(query).matches ?? false,
  );
}
