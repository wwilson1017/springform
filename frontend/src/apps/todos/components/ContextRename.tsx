import { useState } from 'react';
import { ApiError, apiErrorMessage } from '../errors';
import { renameContext } from '../api';

/**
 * Rename one context across the whole list. A context is a string on each
 * to-do, so the server rewrites every to-do carrying it in one step.
 *
 * The server answers 409 when the new name is already a context: the two would merge,
 * which cannot be told apart afterwards, so its sentence is shown with a Merge button
 * and nothing is written until that is pressed. The confirmation is held WITH the name it
 * was given for and counts only while the box still reads that name — an answer that lands
 * after the user typed something else must not arm Merge for the new text. Cancel and
 * Escape are off while a write is in flight: closing then would look like calling it off,
 * and the rename (or merge) would still land.
 */
export function ContextRename({ context, onRenamed }: {
  context: string;
  onRenamed: (next: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(context);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<{ name: string; text: string } | null>(null);
  const [error, setError] = useState('');

  const close = () => { setOpen(false); setConfirm(null); setError(''); };
  const confirming = confirm !== null && confirm.name === name.trim();

  const submit = async (merge: boolean) => {
    const next = name.trim();
    if (!next) { setError('A context name is required.'); return; }
    if (next === context) { close(); return; }
    setBusy(true);
    setError('');
    try {
      await renameContext(context, next, merge);
      close();
      onRenamed(next);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setConfirm({ name: next, text: apiErrorMessage(e, `"${next}" already exists.`) });
      } else {
        setError(apiErrorMessage(e, 'Could not rename the context.'));
      }
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => { setName(context); setConfirm(null); setOpen(true); }}
        aria-label={`Rename context ${context}`}
        className="rounded px-1.5 py-0.5 text-xs text-sf-ink-dim underline hover:text-sf-ink"
      >
        Rename
      </button>
    );
  }

  return (
    <form
      onSubmit={e => { e.preventDefault(); void submit(false); }}
      className="mt-1 flex w-full flex-wrap items-center gap-2 text-sm"
    >
      <input
        autoFocus
        value={name}
        maxLength={500}
        onChange={e => { setName(e.target.value); setConfirm(null); setError(''); }}
        onKeyDown={e => { if (e.key === 'Escape' && !busy) close(); }}
        aria-label={`New name for context ${context}`}
        className="min-w-0 grow rounded-lg border border-sf-line-strong bg-sf-card px-2 py-1.5 text-sf-ink focus:border-sf-accent focus:outline-none"
      />
      {confirming ? (
        <button type="button" disabled={busy} onClick={() => void submit(true)}
                className="rounded-lg bg-sf-accent px-3 py-1.5 font-display text-sf-accent-ink hover:bg-sf-accent-dark disabled:opacity-40">
          Merge
        </button>
      ) : (
        <button type="submit" disabled={busy}
                className="rounded-lg bg-sf-accent px-3 py-1.5 font-display text-sf-accent-ink hover:bg-sf-accent-dark disabled:opacity-40">
          Save
        </button>
      )}
      <button type="button" disabled={busy} onClick={close}
              className="px-2 py-1.5 text-sf-ink-dim hover:text-sf-ink disabled:opacity-40">
        Cancel
      </button>
      {(confirming || error) && (
        <p role="alert" className={`w-full ${error ? 'text-sf-red-text ' : 'text-sf-ink'}`}>
          {error || confirm?.text}
        </p>
      )}
    </form>
  );
}
