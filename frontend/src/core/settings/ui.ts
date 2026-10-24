import { ApiError } from '../api/client';

// Form classes shared by the Settings cards and the Backups page.
export const labelClass = 'mb-1 block text-xs font-medium text-sf-ink-soft';
export const inputClass =
  'box-border w-full rounded-md border border-sf-line-strong bg-sf-card px-3 py-2 text-sm text-sf-ink placeholder:text-sf-ink-dim';
export const buttonClass =
  'cursor-pointer rounded-md border-0 bg-sf-accent px-3.5 py-2 text-sm font-medium text-sf-accent-ink disabled:cursor-default disabled:opacity-50';
export const secondaryButtonClass =
  'cursor-pointer rounded-md border border-sf-line-strong bg-transparent px-3 py-1.5 text-sm text-sf-ink hover:bg-sf-hover disabled:cursor-default disabled:opacity-50';
export const chipClass = 'rounded bg-sf-ink/6 px-1.5 py-0.5 text-xs text-sf-ink-soft';
export const errorTextClass = 'm-0 text-sm text-sf-red-text';

/** The server's `{detail}` for a refusal, or a generic line for anything else. */
export const errorText = (e: unknown, fallback = "Couldn't save. Try again."): string =>
  e instanceof ApiError && e.status < 500 ? e.detail : fallback;
