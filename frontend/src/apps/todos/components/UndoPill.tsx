// Todo GTD — the undo block (todo-gtd #2879 mark-done, todo-gtd #2925 inbox triage; design locked
// to prototype C2).
//
// ONE framed object, not a pile of toasts. A persistent header that never moves
// carries the running count and (once there is more than one row) "Undo all";
// each undoable action adds a FIXED-HEIGHT row below it. So the block grows and
// shrinks vertically only — the fixed width plus the truncated titles are what
// stop it resizing under the cursor, which was the specific objection to the
// stacked-toast treatment this replaces.
//
// Mounted once by `TodoShell`, fed by the module-level queue in `undoQueue.ts` —
// so it survives the shell's remount on every tab switch and a completion on
// Today is still undoable after the user moves to Inbox.
import { undoAll, undoOne } from '../hooks';
import { useUndoQueue, type UndoKind } from '../undoQueue';
import { useTodoOwner } from '../useTodoMeta';

// The one place the two undoable actions are named. `row` labels the row, which
// todo-gtd #2925 asks for in as many words; `header` is the same fact in the plural, for
// the count line. Copy, so it lives in the component and not in the store.
const KIND: Record<UndoKind, { row: string; header: string; verb: (title: string) => string }> = {
  done: {
    row: 'Marked done',
    header: 'marked done',
    verb: title => `Undo marking “${title}” done`,
  },
  filed: {
    row: 'Context set',
    header: 'filed from inbox',
    verb: title => `Undo filing “${title}”`,
  },
};

// Rows are h-11 (44px) rather than something tighter, and one value for both
// breakpoints keeps "fixed row height" literally true.
const ROW = 'flex h-11 items-center gap-2 px-3';
// The BUTTON is the tap target, not the row — the row has no click handler, so a
// compact button inside a 44px row leaves dead bands above and below it that
// swallow a thumb (measured at 8px each on a 390px viewport before this was
// fixed). `min-h-11` makes the button fill the row on mobile, where C2 asks for
// large targets; from `sm` up it relaxes to the compact desktop size.
const ACTION =
  'shrink-0 inline-flex items-center justify-center min-h-11 sm:min-h-0 rounded-lg ' +
  'px-3 sm:px-2 py-1 text-sm font-display font-semibold text-sf-accent-text ' +
  'hover:bg-sf-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-sf-accent';

/** `inline` = sit in the page flow at full width (the Inbox, under the triage card)
 *  instead of floating in the shell's bottom stack. */
export function UndoPill({ inline = false }: { inline?: boolean }) {
  // Owner-filtered during render, so a tab that changes hands mid-session never
  // paints the previous occupant's todo title (see `undoQueue.useUndoQueue`).
  const entries = useUndoQueue(useTodoOwner());
  if (entries.length === 0) return null;

  // The header names the action while every row is the same one, which keeps
  // todo-gtd #2879's wording exactly where it was; a queue holding both kinds has no one
  // action to name, and the per-row labels are what disambiguate it there.
  const onlyKind = entries.every(e => e.kind === entries[0].kind) ? entries[0].kind : null;
  const heading = onlyKind
    ? `${entries.length} ${KIND[onlyKind].header}`
    : `${entries.length} recent changes`;

  return (
    <div
      // `role="status"` + polite: the action is worth announcing, but never
      // worth interrupting what the screen reader is already saying.
      role="status"
      aria-live="polite"
      aria-label="Recent changes you can undo"
      className={`overflow-hidden rounded-xl border border-sf-line-strong bg-sf-card ${inline
        ? 'mt-4 w-full'
        : 'pointer-events-auto w-full max-w-sm shadow-lg sm:w-80 sm:self-end'}`}
    >
      <div className="flex h-11 items-center justify-between gap-2 border-b border-sf-line px-3">
        <span className="truncate font-display text-sm font-semibold text-sf-ink">
          {heading}
        </span>
        {/* Only once it stops being a second button for the same single row. */}
        {entries.length > 1 && (
          <button type="button" onClick={() => void undoAll()} className={ACTION}>
            Undo all
          </button>
        )}
      </div>
      <ul>
        {entries.map(entry => (
          <li key={entry.key} className={ROW}>
            {/* `min-w-0` is what lets `truncate` actually clip inside a flex row —
                without it the title sets the block's width and C2's fixed width
                is gone. */}
            <span className="min-w-0 flex-1 truncate text-sm text-sf-ink-dim" title={entry.title}>
              {entry.title}
            </span>
            {/* What happened to it. `shrink-0` so the title, not the label, is
                what gives way when the block runs out of room. */}
            <span className="shrink-0 text-xs text-sf-ink-dim">{KIND[entry.kind].row}</span>
            <button
              type="button"
              onClick={() => void undoOne(entry.key)}
              // "Undo?" alone names nothing when the rows are read out of context,
              // and the two kinds undo different things.
              aria-label={KIND[entry.kind].verb(entry.title)}
              className={ACTION}
            >
              Undo?
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
