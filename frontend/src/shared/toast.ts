/**
 * Toast store. A module-level singleton so `toast.error(...)` is callable from anywhere (hooks,
 * fire-and-forget `.catch()` handlers) without threading React context. `ToastViewport`, mounted
 * once in Root, renders the stack via `useSyncExternalStore`.
 */

export type ToastSeverity = 'error' | 'success' | 'info';

export interface ToastItem {
  id: number;
  severity: ToastSeverity;
  message: string;
  duration: number;
}

const MAX_TOASTS = 5;

let toasts: ToastItem[] = [];
let listeners: Array<() => void> = [];
let nextId = 1;

function emit() {
  for (const listener of listeners) listener();
}

export function subscribeToasts(onChange: () => void): () => void {
  listeners.push(onChange);
  return () => {
    listeners = listeners.filter(l => l !== onChange);
  };
}

export function getToasts(): ToastItem[] {
  return toasts;
}

export function dismissToast(id: number) {
  if (!toasts.some(t => t.id === id)) return;
  toasts = toasts.filter(t => t.id !== id);
  emit();
}

function push(severity: ToastSeverity, message: string, duration: number) {
  toasts = [...toasts, { id: nextId++, severity, message, duration }].slice(-MAX_TOASTS);
  emit();
}

export const toast = {
  error: (message: string) => push('error', message, 7000),
  success: (message: string) => push('success', message, 4000),
  info: (message: string) => push('info', message, 4000),
};
