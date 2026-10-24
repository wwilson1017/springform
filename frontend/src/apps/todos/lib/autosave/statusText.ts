import type { AutoSaveStatus } from './types';

/** Status → the colour it is announced in. Idle states stay quiet; failures are tinted. */
export const STATUS_TONE: Record<AutoSaveStatus, string> = {
  idle: 'text-sf-ink-dim',
  dirty: 'text-sf-ink-dim',
  saving: 'text-sf-ink-dim',
  saved: 'text-sf-ink-dim',
  conflict: 'text-sf-amber-text',
  error: 'text-sf-red-text ',
};

/** The words themselves — a pure function so a test can pin the copy without a DOM. */
export function saveStatusText(status: AutoSaveStatus, errorMessage?: string | null): string {
  switch (status) {
    case 'dirty':
      return 'Unsaved changes';
    case 'saving':
      return 'Saving…';
    case 'conflict':
      // Deliberately NOT "edited by someone else": the same 409 arrives when a save
      // committed but its response was lost and the retry re-sent a now-stale token, where
      // the other editor is you. This is the string a screen reader speaks, so it must not
      // assert something the client cannot know.
      return 'Not saved — this record changed';
    case 'error':
      return errorMessage ? `Not saved — ${errorMessage}` : 'Not saved';
    default:
      return 'All changes saved';
  }
}
