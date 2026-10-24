/**
 * The CRM's modal shell: a portal to `document.body` (so no ancestor's stacking context traps
 * it), Escape to cancel (capture phase, so it never also closes something underneath), a Tab
 * trap, the first field focused, and focus restored on close.
 */
import { useEffect, useId, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

export function Dialog({ title, subtitle, onClose, children, wide }: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const onCloseRef = useRef(onClose);
  useEffect(() => { onCloseRef.current = onClose; });

  useEffect(() => {
    const previouslyFocused = document.activeElement;
    const focusable = () => [...(ref.current?.querySelectorAll<HTMLElement>(
      'input, textarea, select, button, [href], [tabindex]:not([tabindex="-1"])',
    ) ?? [])].filter(el => !(el as HTMLButtonElement).disabled);
    (focusable().find(el => el.matches('input, textarea, select')) ?? focusable()[0])?.focus();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (e.key !== 'Tab') return;
      const els = focusable();
      if (els.length === 0) return;
      const first = els[0];
      const last = els[els.length - 1];
      const active = document.activeElement;
      if (!(active instanceof Node && ref.current?.contains(active))) {
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
      } else if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener('keydown', onKeyDown, { capture: true });
    return () => {
      document.removeEventListener('keydown', onKeyDown, { capture: true });
      if (previouslyFocused instanceof HTMLElement && document.contains(previouslyFocused)) previouslyFocused.focus();
    };
  }, []);

  return createPortal(
    <div onClick={onClose} className="fixed inset-0 z-[150] flex items-end justify-center bg-sf-scrim md:items-center md:p-4">
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={e => e.stopPropagation()}
        className={`max-h-[90dvh] w-full overflow-y-auto rounded-t-xl border border-sf-line-strong bg-sf-card p-5 shadow-xl md:rounded-lg md:p-6 ${wide ? 'md:max-w-3xl' : 'md:max-w-md'}`}
      >
        <h2 id={titleId} className="m-0 font-display text-lg font-medium text-sf-ink">{title}</h2>
        {subtitle && <p className="m-0 mt-1 text-sm text-sf-ink-mute">{subtitle}</p>}
        <div className="mt-4">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
