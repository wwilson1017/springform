import type { SaveStatusProps } from './types';
import { STATUS_TONE, saveStatusText } from './statusText';

/**
 * The ambient "All changes saved" line (#2032) — the reassurance half of auto-save.
 *
 * It is the surface's ONE announcer: it carries `aria-live`, so a caller rendering its own
 * banner for the same failure must leave that banner silent, or every error is read twice.
 */
export function SaveStatus({ status, errorMessage, className = '' }: SaveStatusProps) {
  return (
    <span aria-live="polite" className={`text-xs ${STATUS_TONE[status]} ${className}`.trim()}>
      {saveStatusText(status, errorMessage)}
    </span>
  );
}
