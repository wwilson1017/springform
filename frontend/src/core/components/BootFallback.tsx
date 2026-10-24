/**
 * The loading state for every Suspense gap (cold boot, a lazy route, a lazy card) and the auth
 * check, so a chunk load and an auth check look like one app.
 *
 * `role="status"` + the visually-hidden text is what gives a screen-reader user the signal at
 * all; without it a slow cold boot is silence.
 *
 * `variant`: 'page' fills the viewport; 'panel' pads inside an already-rendered container.
 */
export default function BootFallback({ variant = 'page' }: { variant?: 'page' | 'panel' }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={`flex items-center justify-center bg-sf-bg text-sf-ink-mute ${
        variant === 'page' ? 'min-h-svh' : 'py-16'
      }`}
    >
      <div className="w-8 h-8 border-2 border-sf-accent-text border-t-transparent rounded-full animate-spin" />
      <span className="sr-only">Loading…</span>
    </div>
  );
}
