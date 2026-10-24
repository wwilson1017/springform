import { Component, createRef, type ErrorInfo, type ReactNode } from 'react';

/** sessionStorage: survives a reload of THIS tab ("one attempt per tab session") and dies with it. */
export const RELOAD_GUARD_KEY = 'springform_chunk_reload';

/**
 * Did a chunk fail to LOAD (fixed by reloading after a deploy), rather than a component throw
 * while rendering? Browsers give no code, so the message is the only signal. Matching
 * conservatively is the safe direction: a missed chunk error costs one click, while reloading on
 * a render bug replays the crash and hides it.
 */
function isChunkLoadError(error: unknown): boolean {
  return /dynamically imported module|Importing a module script failed|error loading dynamically|Unable to preload CSS/i
    .test(errorMessage(error));
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'object' && error !== null && 'message' in error) {
    return String((error as { message: unknown }).message ?? '');
  }
  return String(error ?? '');
}

type Props = {
  children: ReactNode;
  /**
   * How much of the screen this boundary speaks for. `Suspense` catches a PENDING import, never
   * a REJECTED one, so every `lazy()` needs a boundary above it.
   * - 'app' (default): the one in Root; full-page card and a one-shot auto-reload.
   * - 'route': the shell's content column; compact card, one-shot reload, nav survives.
   * - 'panel': a non-essential subtree (a settings card, a record panel); compact card and
   *   NEVER an auto-reload, because the user did not ask for it.
   */
  scope?: 'app' | 'route' | 'panel';
  /** Changing it clears a caught error (the route boundary passes the pathname). */
  resetKey?: string;
};
type State = { failed: boolean; chunk: boolean; offline: boolean; resetKey?: string };

export default class ChunkErrorBoundary extends Component<Props, State> {
  state: State = { failed: false, chunk: false, offline: false };

  static getDerivedStateFromError(error: Error): State {
    return {
      failed: true,
      chunk: isChunkLoadError(error),
      offline: typeof navigator !== 'undefined' && navigator.onLine === false,
    };
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    if (props.resetKey === state.resetKey) return null;
    return state.failed
      ? { failed: false, chunk: false, offline: false, resetKey: props.resetKey }
      : { resetKey: props.resetKey };
  }

  private readonly alertRef = createRef<HTMLDivElement>();

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Render failed below ChunkErrorBoundary', error, info.componentStack);
    if (this.props.scope === 'panel') return;
    // Offline: a reload cannot fetch the chunk either, so leave the card up.
    const online = typeof navigator === 'undefined' || navigator.onLine !== false;
    if (isChunkLoadError(error) && online && this.claimReloadAttempt()) window.location.reload();
  }

  componentDidMount() {
    if (this.state.failed) this.alertRef.current?.focus();
  }

  componentDidUpdate(_prev: Props, prevState: State) {
    if (!prevState.failed && this.state.failed) this.alertRef.current?.focus();
  }

  /**
   * At most one automatic reload per tab session. The guard never expires: if a chunk is
   * genuinely gone, an expiring guard becomes a reload loop. Storage that is blocked or does not
   * persist the write means no reload, for the same reason.
   */
  private claimReloadAttempt(): boolean {
    try {
      if (sessionStorage.getItem(RELOAD_GUARD_KEY) !== null) return false;
      sessionStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()));
      return sessionStorage.getItem(RELOAD_GUARD_KEY) !== null;
    } catch {
      return false;
    }
  }

  render() {
    if (!this.state.failed) return this.props.children;

    const { chunk, offline } = this.state;
    if (this.props.scope === 'route' || this.props.scope === 'panel') {
      const what = this.props.scope === 'panel' ? 'panel' : 'page';
      return (
        <div
          ref={this.alertRef}
          role="alert"
          tabIndex={-1}
          className="flex flex-col items-center justify-center gap-3 p-6 text-center text-sf-ink-mute"
        >
          <p className="m-0">
            {this.headline(chunk, what)} {this.explain(chunk, offline, `this ${what}`)}
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="bg-sf-accent hover:bg-sf-accent-dark text-sf-accent-ink font-display px-4 py-1.5 rounded cursor-pointer border-0"
          >
            Reload the page
          </button>
        </div>
      );
    }
    return (
      <div
        ref={this.alertRef}
        role="alert"
        tabIndex={-1}
        className="min-h-svh bg-sf-bg flex flex-col items-center justify-center gap-4 p-6 text-center"
      >
        <h1 className="text-sf-ink font-display text-lg m-0">{this.headline(chunk, 'page')}</h1>
        <p className="text-sf-ink-mute max-w-sm m-0">{this.explain(chunk, offline, 'this page')}</p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="bg-sf-accent hover:bg-sf-accent-dark text-sf-accent-ink font-display px-5 py-2 rounded cursor-pointer border-0"
        >
          Reload
        </button>
      </div>
    );
  }

  private headline(chunk: boolean, what: string): string {
    if (chunk) return `Couldn’t load this ${what}.`;
    return what === 'page' ? 'Something went wrong on this page.' : `Something went wrong in this ${what}.`;
  }

  private explain(chunk: boolean, offline: boolean, what: string): string {
    if (chunk && offline) return `You appear to be offline, so ${what} couldn’t load. Reconnect, then reload.`;
    if (chunk) return 'This usually means the app was updated while your tab was open. Reloading gets the latest version.';
    return 'Reloading may help. If it keeps happening, report it: this one is a bug, not an update.';
  }
}
