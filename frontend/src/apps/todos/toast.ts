// Todo GTD — minimal transient toasts (module pub/sub, same pattern as
// useTodoMeta's listeners). Rendered by <Toasts/> in TodoShell; used for
// failures on one-click row actions (which have no inline error surface)
// and the reopen-a-repeat notice.
import { useEffect, useState } from 'react';

export interface ToastMsg {
  id: number;
  kind: 'info' | 'error';
  text: string;
}

let nextId = 1;
let current: ToastMsg[] = [];
const timers = new Map<number, ReturnType<typeof setTimeout>>();
const listeners = new Set<(t: ToastMsg[]) => void>();

function push(kind: ToastMsg['kind'], text: string) {
  const msg = { id: nextId++, kind, text };
  current = [...current, msg];
  listeners.forEach(l => l(current));
  timers.set(msg.id, setTimeout(() => {
    timers.delete(msg.id);
    current = current.filter(t => t.id !== msg.id);
    listeners.forEach(l => l(current));
  }, 5000));
}

export const toast = {
  info: (text: string) => push('info', text),
  error: (text: string) => push('error', text),
};

/** Drop every toast on screen, timers and all. For tests: `current` is module
 *  state and each toast's 5s expiry is a fake timer the previous test's
 *  `useRealTimers()` already threw away, so without this a message raised in one
 *  case is still rendered in the next and any assertion about what the user is
 *  being told reads the wrong test's output. The undo queue exports its reset for
 *  the same reason. */
export function resetToasts() {
  current.forEach(t => clearTimeout(timers.get(t.id)));
  timers.clear();
  current = [];
  listeners.forEach(l => l(current));
}

export function useToasts(): ToastMsg[] {
  const [toasts, setToasts] = useState<ToastMsg[]>(current);
  useEffect(() => {
    const listener = (t: ToastMsg[]) => setToasts(t);
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  }, []);
  return toasts;
}
