import { parseTags } from '../util';

interface Props {
  /** Comma-separated, entered exactly the way tags are. */
  value: string;
  onChange: (value: string) => void;
  /** People already named on this list (the filters payload). */
  suggestions: string[];
  id?: string;
  /** Accessible name where there is no visible <label> (the triage card). */
  label?: string;
  className?: string;
  disabled?: boolean;
  onBlur?: () => void;
  /** A suggestion was clicked; receives the value it produced. */
  onPick?: (value: string) => void;
  /** The tags field reuses this input with its own example. */
  placeholder?: string;
}

const MAX_OFFERED = 8;

/** Who a todo involves: the tags field's comma-separated input, plus one-tap
 *  suggestions of people the list already knows. Typing narrows them; a name
 *  that is not among them is simply a new person. */
export function PeopleInput({
  value, onChange, suggestions, id, label, className = '', disabled, onBlur, onPick,
  placeholder = 'Ana, Bo',
}: Props) {
  const parts = value.split(',');
  const last = parts[parts.length - 1].trim();
  // What follows the last comma is a search — unless it is already a known person's
  // whole name, which is a finished entry (so "Bo" does not hide everyone but "Bob").
  const typing = suggestions.includes(last) ? '' : last.toLowerCase();
  const entered = parseTags(value);
  const offered = suggestions
    .filter(s => !entered.includes(s) && s.toLowerCase().includes(typing))
    .slice(0, MAX_OFFERED);

  /** The name replaces the fragment being typed, or joins the finished entries. */
  const pick = (name: string) => {
    const kept = typing ? parts.slice(0, -1) : parts;
    const next = [...parseTags(kept.join(',')), name].join(', ');
    onChange(next);
    onPick?.(next);
  };

  return (
    <>
      <input
        id={id}
        aria-label={label}
        className={className}
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        onChange={e => onChange(e.target.value)}
        onBlur={onBlur}
      />
      {offered.length > 0 && (
        <span className="mt-1 flex flex-wrap gap-1" data-people-suggestions>
          {offered.map(name => (
            <button
              key={name}
              type="button"
              disabled={disabled}
              // Keep focus in the input: a blur here would commit the half-typed
              // fragment this click is about to replace.
              onMouseDown={e => e.preventDefault()}
              onClick={() => pick(name)}
              className="rounded-full border border-sf-line-strong px-2 py-0.5 text-xs text-sf-ink-dim hover:bg-sf-hover hover:text-sf-ink disabled:opacity-50"
            >
              + {name}
            </button>
          ))}
        </span>
      )}
    </>
  );
}
