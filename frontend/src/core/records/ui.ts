/** Tailwind class strings the record-service screens share, so a button looks the same on each. */
import { ApiError } from '../api/client';

export const INPUT =
  'box-border w-full rounded-md border border-sf-line-strong bg-sf-card px-3 py-1.5 font-sans text-sm text-sf-ink placeholder:text-sf-ink-dim disabled:opacity-60';
export const LABEL = 'mb-1 block text-xs font-medium text-sf-ink-mute';
export const BTN_PRIMARY =
  'cursor-pointer rounded-md border-0 bg-sf-accent px-4 py-1.5 font-sans text-sm font-medium text-sf-accent-ink disabled:cursor-default disabled:opacity-50';
export const BTN_SECONDARY =
  'cursor-pointer rounded-md border border-sf-line-strong bg-transparent px-3 py-1.5 font-sans text-sm text-sf-ink-mute hover:bg-sf-hover disabled:cursor-default disabled:opacity-50';
export const BTN_LINK =
  'cursor-pointer border-0 bg-transparent p-0 font-sans text-xs text-sf-accent-text hover:underline disabled:cursor-default disabled:opacity-50';
export const BTN_DANGER_LINK =
  'cursor-pointer border-0 bg-transparent p-0 font-sans text-xs text-sf-red-text hover:underline disabled:cursor-default disabled:opacity-50';
export const H_SECTION = 'm-0 mb-3 font-display text-base font-medium text-sf-ink';
export const PAGE = 'mx-auto max-w-5xl px-4 py-8 md:px-8';
export const H_PAGE = 'm-0 font-display text-2xl font-medium text-sf-ink';
export const MUTED = 'm-0 text-sm text-sf-ink-dim';

/** A refusal's `detail` (4xx: nothing was written), else `fallback`. */
export function errorText(err: unknown, fallback: string): string {
  return err instanceof ApiError && err.status < 500 && err.detail ? err.detail : fallback;
}
