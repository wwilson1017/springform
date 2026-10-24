/**
 * Copy text to the clipboard, with a transient "copied" / "failed" flag.
 *
 * `navigator.clipboard` only exists in a secure context. The app is also reached
 * over plain http on a LAN or Tailscale address, where it is undefined — so every
 * copy button goes through `copyToClipboard`, which falls back to the legacy
 * selection + execCommand path, and reports failure instead of hiding it.
 */
import { useState, useCallback, useRef, useEffect } from 'react';

/** execCommand('copy') from an off-screen textarea. Works without a secure context,
 *  but only inside a user gesture. */
function legacyCopy(text: string): boolean {
  const active = document.activeElement as HTMLElement | null;
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.readOnly = true; // no on-screen keyboard on phones
  ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
  document.body.appendChild(ta);
  ta.focus({ preventScroll: true }); // the selection must be the focused one to be copied
  ta.select();
  ta.setSelectionRange(0, text.length); // iOS ignores select() on its own
  try {
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    ta.remove();
    active?.focus?.();
  }
}

/** Resolves true when the text reached the clipboard by either route. */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // No clipboard API (non-secure context) or permission refused.
    return legacyCopy(text);
  }
}

export type CopyState = 'idle' | 'copied' | 'failed';

export function useCopyToClipboard(resetMs = 1500) {
  const [state, setState] = useState<CopyState>('idle');
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const copy = useCallback(async (text: string) => {
    const ok = await copyToClipboard(text);
    setState(ok ? 'copied' : 'failed');
    if (timerRef.current) clearTimeout(timerRef.current);
    // A failure stays up longer: it carries an instruction, not a confirmation.
    timerRef.current = setTimeout(() => setState('idle'), ok ? resetMs : 4000);
  }, [resetMs]);

  // The reset timer outlives the component otherwise: copy, then close the sheet
  // inside `resetMs` and the timeout fires against an unmounted component.
  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  return { state, copied: state === 'copied', failed: state === 'failed', copy };
}
