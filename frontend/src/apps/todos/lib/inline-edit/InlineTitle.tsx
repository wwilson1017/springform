// Click-to-rename title.
//
// Presentational on purpose: it owns the editing/draft state and hands a validated title
// back, so the CALLER keeps one busy/error surface for every write on its card. Rewriting a
// vague capture into a real next action is the most common clarification edit; the full
// editor stays available for everything else.
//
// The `body` VARIANT is the same control over a multi-line free-text field (a project's
// notes). The two differ in exactly three behaviours and share every hard part: the
// draft/closed/refocus state machine, the IME guard, the refuse-and-stay-open path and the
// post-refusal focus recovery.
import { useCallback, useEffect, useRef, useState } from 'react';

// Neither alias below is exported: no consumer annotates with one (both reach a caller as an
// inferred literal), and an export nobody imports reads as proven API — `shared/autosave`'s
// todo-gtd #1059 rule.

/**
 * Which kind of field this is. It decides the three things a title and a body disagree about
 * and nothing else:
 *
 *   * `title` — Enter saves (Shift+Enter is the newline escape hatch), and an emptied value is
 *     a slip that never reaches the caller.
 *   * `body` — Enter inserts a newline like any textarea, so blur and Escape are the only
 *     exits, and an emptied value is a legitimate save: clearing a notes field is something a
 *     user means, not a mistake, and a field that cannot be emptied is broken.
 */
type InlineEditVariant = 'title' | 'body';

/** Why the editor closed with nothing written — see `onCancel`. */
type InlineEditCancelReason = 'escape' | 'blank' | 'unchanged';

interface Props {
  title: string;
  /**
   * Accessible name for the editor. A PROP rather than the hardcoded "Todo title" this
   * carried in todo-gtd: two apps now render it and the control has to say which record it
   * renames ("Todo title", "Request title").
   */
  label: string;
  /** Typography of the static text — the editor mirrors it so nothing jumps. */
  className?: string;
  disabled?: boolean;
  variant?: InlineEditVariant;
  /**
   * What the trigger shows while the value is empty, so an empty field is still something to
   * click. Without it an empty value renders a zero-width button nobody can hit — which is
   * why Todo GTD's project notes did not render AT ALL when blank before todo-gtd #3198.
   */
  placeholder?: string;
  /** Persist the edit; resolves false if the write failed. An unchanged value never reaches
   * it, and neither does a blank one unless `variant="body"`. */
  onSave: (value: string) => Promise<boolean>;
  /**
   * The editor closed WITHOUT saving, and WHY.
   *
   * Exists so a caller holding a failure banner can clear it: a refused save leaves this
   * control open with the typed text, and pressing Escape from there used to close the
   * editor while the caller's "could not save" line stayed on screen under the restored
   * title, with no gesture left that would dismiss it (todo-gtd #1908 review).
   *
   * The reason was added by todo-gtd #3198, whose gate requires that a blank name be REFUSED VISIBLY
   * rather than reverting in silence. The caller cannot work that out for itself — it never
   * sees the draft — and the argument is optional to receive, so the zero-parameter handlers
   * that predate it still type-check and still behave identically.
   */
  onCancel?: (reason: InlineEditCancelReason) => void;
}

export function InlineTitle({
  title, label, className = '', disabled = false,
  variant = 'title', placeholder, onSave, onCancel,
}: Props) {
  // The two variant-driven behaviours, named once so the branches below read as intent.
  const commitsOnEnter = variant === 'title';
  const allowEmpty = variant === 'body';
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState(title);
  // Enter and Escape both close the editor, and closing blurs it — this keeps
  // the trailing blur from re-running (or undoing) the decision already made.
  const closed = useRef(false);
  // Only a KEYBOARD finish returns focus. On blur the user has already clicked
  // somewhere else, and stealing focus back mid-click can eat that click.
  const refocus = useRef(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  // Set when a save is REFUSED, consumed by the effect below.
  const recoverFocus = useRef(false);

  // Stable identity so React runs it once on mount — a per-render callback
  // would re-place the caret on every keystroke.
  const focusEnd = useCallback((el: HTMLTextAreaElement | null) => {
    editorRef.current = el;
    if (!el) return;
    el.focus();
    // Caret at the end: clicking in to amend a title is the common case.
    el.setSelectionRange(el.value.length, el.value.length);
  }, []);

  useEffect(() => {
    if (editing || !refocus.current) return;
    refocus.current = false;
    triggerRef.current?.focus();
  }, [editing]);

  /*
   * Put focus BACK in the editor after a refused save (todo-gtd #1908 final review).
   *
   * `saving` disables the textarea, and the browser answers that by blurring it to `<body>`.
   * Staying open with the typed text is then only half the promise: the editor is open but
   * unfocused, so the next Escape — the natural way to dismiss the failure — reaches whatever
   * owns the page's Escape stack instead. Inside a `shared/overlay/DetailModal` that closes
   * the whole overlay and discards exactly the text this branch exists to protect.
   *
   * It has to be an EFFECT, not a `focus()` call at the point of failure: `setSaving(false)`
   * is not applied until React re-renders, so focusing there would target a textarea that is
   * still `disabled` — a silent no-op, which is what the first version of this fix was.
   */
  useEffect(() => {
    if (!editing || saving || !recoverFocus.current) return;
    recoverFocus.current = false;
    editorRef.current?.focus();
  }, [editing, saving]);

  const start = () => {
    if (disabled) return;
    setDraft(title);
    closed.current = false;
    setEditing(true);
  };

  const finish = async (commit: boolean, keyboard = false) => {
    if (closed.current) return;
    closed.current = true;
    // A TITLE is trimmed on the way out. A BODY is not: the field it edits stores free text
    // verbatim (todo_gtd's `validate_notes` returns it untouched), so trimming would silently
    // drop the indent someone typed on the first line of a list, and every trailing newline —
    // rewriting what they wrote on save. A draft that is ENTIRELY whitespace still normalizes
    // to empty, because a trigger rendering three spaces is an invisible control and the
    // placeholder is what makes an empty field clickable.
    const next = commitsOnEnter || draft.trim() === '' ? draft.trim() : draft;
    // An emptied title is a slip, not a request — and the API rejects it anyway. A `body`
    // field is the opposite: clearing notes is a real edit, so it commits.
    const blank = !next && !allowEmpty;
    //
    // A title's baseline is `title.trim()`, NOT `title` (todo-gtd #1908 review). A STORED title carrying
    // incidental whitespace is otherwise "changed" the instant the editor closes, so merely
    // opening and blurring one would issue a real write — and on Maintenance that write is a
    // correction on a Tier-1 audit chain, attributed to whoever happened to tap the title.
    // The bug was unreachable in todo-gtd (its service trims every title on write, so no
    // stored title carries padding); Maintenance is what makes it reachable. A body compares
    // RAW for the same reason it saves raw — trimming one side only would make an edit that
    // adds a trailing newline compare equal and never save. Either way, opening and blurring
    // an EMPTY body field stays silent: "" === "" is unchanged.
    if (!commit || blank || next === (commitsOnEnter ? title.trim() : title)) {
      refocus.current = keyboard;
      setEditing(false);
      // Escape wins the label when both apply: the user asked to abandon the edit, so
      // telling them the draft they discarded was also blank would be noise.
      onCancel?.(!commit ? 'escape' : blank ? 'blank' : 'unchanged');
      return;
    }
    setSaving(true);
    const ok = await onSave(next);
    setSaving(false);
    if (ok) {
      refocus.current = keyboard;
      setEditing(false);
      return;
    }
    // The write failed. Stay open with the text intact — discarding what the
    // user just typed and reverting to the old title loses their work, and a
    // rename is usually the whole reason they opened the card.
    closed.current = false;
    // ...and ask for focus back, once React has re-enabled the textarea (see the effect).
    recoverFocus.current = true;
  };

  if (editing) {
    return (
      <textarea
        ref={focusEnd}
        rows={commitsOnEnter ? 2 : 4}
        value={draft}
        disabled={saving}
        aria-label={label}
        onChange={e => setDraft(e.target.value)}
        onBlur={() => void finish(true)}
        onKeyDown={e => {
          // Both keys carry the IME guard, not just Enter (todo-gtd #1908 review): Escape is how a
          // Japanese / Chinese / Korean writer dismisses an active conversion CANDIDATE, so
          // without it the first Escape throws away the whole title edit instead of the
          // suggestion the writer was rejecting.
          if (e.nativeEvent.isComposing) return;
          // Swallow ONLY the two keys this editor actually claims. It used to stop every
          // keydown — harmless on the kanban card it was written for, but this now renders
          // inside `shared/overlay/DetailModal`, whose focus TRAP is a React onKeyDown on the
          // panel. Stopping the synthetic event there means Shift+Tab off the open textarea
          // (the first focusable in the dialog on desktop) walks out of the modal entirely,
          // breaking the compensating control it relies on for not setting `aria-modal`
          // (todo-gtd #1908 final review).
          // A `body` field claims Escape only: its Enter is an ordinary newline, so the
          // keystroke must reach the textarea's own default AND keep bubbling exactly as
          // every other key in it does.
          if (e.key !== 'Escape' && !(e.key === 'Enter' && commitsOnEnter)) return;
          // The card and the page above it have their own Escape handling.
          e.stopPropagation();
          if (e.key === 'Escape') {
            e.preventDefault();
            void finish(false, true);
          } else if (e.key === 'Enter' && !e.shiftKey) {
            // Shift+Enter stays the newline escape hatch. (The Enter that COMMITS an IME
            // candidate reaches this handler too — the guard above is what stops it saving
            // a half-converted title mid-word. Same rule as `shared/chatter/ChatterComposer`.)
            e.preventDefault();
            void finish(true, true);
          }
        }}
        className={`${className} w-full resize-y rounded border border-sf-accent bg-sf-card px-1 py-0.5 focus:outline-none`}
      />
    );
  }

  return (
    <button
      ref={triggerRef}
      type="button"
      disabled={disabled}
      // No tooltip while disabled — "Click to rename" on a control that cannot rename is a
      // lie the user only discovers by trying it (todo-gtd #1908 review).
      title={disabled ? undefined : commitsOnEnter ? 'Click to rename' : 'Click to edit'}
      // The visible text names this control, as it always has. The fallback is for the one
      // case that leaves nothing to read — an empty value with no placeholder — where the
      // button previously had no accessible name at all. It is NOT applied alongside a
      // placeholder: that would make the name differ from the visible words (WCAG 2.5.3).
      aria-label={title || placeholder ? undefined : label}
      onClick={start}
      // Hug the text — the blank space beside a title isn't a rename target.
      // `break-words` so a pasted URL wraps instead of widening the card.
      className={`${className} inline-block max-w-full break-words rounded border border-transparent px-1 py-0.5 text-left hover:border-sf-line-strong disabled:opacity-50`}
    >
      {title || (placeholder && <span className="italic opacity-80">{placeholder}</span>)}
    </button>
  );
}
