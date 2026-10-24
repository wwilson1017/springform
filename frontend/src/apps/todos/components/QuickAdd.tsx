import { useMemo, useRef, useState } from 'react';
import { apiErrorMessage } from '../errors';
import { createTodo, projectIdFor } from '../api';
import { parseQuickAdd } from '../quickAdd';
import type { QuickAddChip } from '../quickAdd';
import { useListFilters, useListProjects, useListTz } from '../useTodoMeta';
import { zonedNow } from '../util';

interface Props {
  onAdded: () => void;
  /** Link every todo added here to a record (a person's or organization's panel). */
  link?: { entity_type: string; entity_id: number };
  placeholder?: string;
}

const CHIP_STYLES: Record<QuickAddChip['kind'], string> = {
  due: 'bg-sf-ai/15 text-sf-ai-text',
  repeat: 'bg-sf-accent-soft text-sf-accent-text',
  project: 'bg-sf-bg text-sf-ink-dim',
  context: 'bg-sf-bg text-sf-ink-dim',
  star: 'bg-sf-amber/15 text-sf-amber-text',
};

/** One-line capture with live natural-language parsing. Recognized fragments
 * render as removable chips below the input BEFORE submit — visible parse
 * feedback is what makes NL capture trustworthy. Everything lands in the
 * Inbox; parsed fields ride along. */
export function QuickAdd({ onAdded, link, placeholder }: Props) {
  const [input, setInput] = useState('');
  const [ignored, setIgnored] = useState<string[]>([]);
  const [autoStar, setAutoStar] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const tz = useListTz();
  const projects = useListProjects();
  const defaultVisibility = useListFilters()?.default_visibility;
  const parsed = useMemo(
    () => parseQuickAdd(input, zonedNow(tz), ignored),
    [input, ignored, tz],
  );

  const submit = async () => {
    if (!parsed.title.trim() || busy) return;
    setBusy(true);
    setError('');
    const sent = input;
    try {
      // A `#Project` names one the user can see, or makes it (with the todo's visibility, so
      // the pair keeps the hierarchy rule).
      const projectId = parsed.project
        ? await projectIdFor(parsed.project, projects, defaultVisibility ? { visibility: defaultVisibility } : {})
        : null;
      await createTodo({
        ...link,
        title: parsed.title,
        status: 'inbox',
        project_id: projectId,
        context: parsed.context ?? '',
        star: parsed.star,
        due_date: parsed.due_date ?? null,
        repeat: parsed.repeat ?? '',
        auto_star_on_due: parsed.repeat ? autoStar : false,
      });
      // The box stays editable while the add is in flight: clear only the draft that was sent.
      if ((inputRef.current?.value ?? sent) === sent) {
        setInput('');
        setIgnored([]);
        setAutoStar(false);
      }
      onAdded();
      inputRef.current?.focus(); // rapid-fire capture
    } catch (e) {
      setError(apiErrorMessage(e, 'Failed to add'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <form
        onSubmit={e => { e.preventDefault(); void submit(); }}
        className="flex gap-2"
      >
        <input
          ref={inputRef}
          value={input}
          onChange={e => { setInput(e.target.value); setIgnored([]); }}
          placeholder={placeholder ?? 'Add to inbox — try “call Sam tomorrow #House @calls !”'}
          aria-label="Add a todo"
          className="min-w-0 flex-1 rounded-lg border border-sf-line-strong bg-sf-card px-3 py-2 text-base sm:text-sm text-sf-ink placeholder:text-sf-ink-dim focus:border-sf-accent focus:outline-none"
        />
        <button
          type="submit"
          disabled={!parsed.title.trim() || busy}
          className="shrink-0 rounded-lg bg-sf-accent px-4 py-2 text-sm font-display text-sf-accent-ink hover:bg-sf-accent-dark disabled:opacity-40"
        >
          Add
        </button>
      </form>
      {parsed.chips.length > 0 && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {parsed.chips.map((chip, i) => (
            <button
              key={`${chip.raw}-${i}`}
              type="button"
              onClick={() => setIgnored(prev => [...prev, chip.raw.trim()])}
              title="Remove — keeps the words in the title"
              className={`rounded-full px-2 py-0.5 text-xs ${CHIP_STYLES[chip.kind]}`}
            >
              {chip.label} ✕
            </button>
          ))}
        </div>
      )}
      {parsed.repeat && (
        <label className="mt-1.5 flex items-center gap-2 text-xs text-sf-ink-dim">
          <input
            type="checkbox"
            checked={autoStar}
            onChange={e => setAutoStar(e.target.checked)}
            className="h-3.5 w-3.5 accent-sf-amber"
          />
          ★ Star the next occurrence when it comes due today
        </label>
      )}
      {error && <p role="alert" className="mt-1 text-xs text-sf-accent-text">{error}</p>}
    </div>
  );
}
