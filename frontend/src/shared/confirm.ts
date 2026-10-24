/**
 * Styled confirm store, a drop-in for native confirm():
 *
 *   if (!await confirmDialog({ title: 'Delete file', message: '...', danger: true })) return;
 *
 * Module-level singleton (same mechanism as toast.ts). `ConfirmHost`, mounted once in Root,
 * renders the head of the FIFO queue.
 */

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}

export interface PendingConfirm {
  id: number;
  options: ConfirmOptions;
  resolve: (ok: boolean) => void;
}

let queue: PendingConfirm[] = [];
let listeners: Array<() => void> = [];
let nextId = 1;

function emit() {
  for (const listener of listeners) listener();
}

export function subscribeConfirms(onChange: () => void): () => void {
  listeners.push(onChange);
  return () => {
    listeners = listeners.filter(l => l !== onChange);
  };
}

export function getCurrentConfirm(): PendingConfirm | null {
  return queue[0] ?? null;
}

export function settleConfirm(ok: boolean) {
  const head = queue[0];
  if (!head) return;
  queue = queue.slice(1);
  emit();
  head.resolve(ok);
}

export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  // A duplicate trigger (double-click before the overlay paints) resolves false, preserving
  // native confirm()'s one-dialog-one-action semantics. Only the visible head is compared, so a
  // distinct queued action with the same copy is still asked.
  const head = queue[0];
  if (head && head.options.title === options.title && head.options.message === options.message) {
    return Promise.resolve(false);
  }
  return new Promise<boolean>(resolve => {
    queue = [...queue, { id: nextId++, options, resolve }];
    emit();
  });
}
