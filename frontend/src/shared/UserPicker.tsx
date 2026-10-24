/**
 * Pick a user by typing a name: the one user chooser (record owners, the CRM owner filter, user
 * custom fields). It behaves like a <select> whose value is '' or a user id as a string, with
 * fixed `options` above the people for '' or a filter's special values:
 *
 *   <UserPicker id="owner" value={owner} onChange={setOwner} options={[['', 'Nobody']]} />
 *
 * Opening it lists the first people; typing searches. Keyboard: arrows move, Enter picks, Escape
 * closes and keeps the value, Tab leaves. Lifted in behaviour from ContactPicker.
 */
import { useEffect, useId, useState, type KeyboardEvent, type MouseEvent } from 'react';
import type { UserRef } from '../core/api/types';
import { knownName, searchUsers, useUserNames } from './users';

export interface UserPickerProps {
  /** The input's id, for a `<label htmlFor>`. */
  id?: string;
  value: string;
  onChange: (value: string) => void;
  /** Fixed choices above the people, as [value, label]: `['', 'Nobody']`. */
  options?: Array<[string, string]>;
  /** The stored value's name when the caller already has it (a deal's owner_name). A user picked
   *  since reads by the name the search answered. */
  valueName?: string | null;
  'aria-label'?: string;
  disabled?: boolean;
  /** Classes for the input: width and border, as the form around it styles its fields. */
  className?: string;
}

const SEARCH_DELAY_MS = 200;

export function UserPicker({ id, value, onChange, options = [], valueName, 'aria-label': ariaLabel, disabled, className }: UserPickerProps) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [found, setFound] = useState<{ query: string; users: UserRef[]; failed: boolean } | null>(null);
  const [active, setActive] = useState(0);

  const fixed = options.find(([v]) => v === value);
  const userId = !fixed && /^\d+$/.test(value) ? Number(value) : null;
  const nameOf = useUserNames(valueName ? [] : [userId]);
  const current = fixed ? fixed[1] : userId === null ? '' : knownName(userId) ?? (valueName || nameOf(userId));

  const q = query.trim();
  const fresh = found !== null && found.query === q;
  const taken = new Set(options.map(([v]) => v));
  const rows: Array<[string, string]> = [
    ...options.filter(([, label]) => label.toLowerCase().includes(q.toLowerCase())),
    ...(fresh ? found.users.filter(u => !taken.has(String(u.id))).map(u => [String(u.id), u.name] as [string, string]) : []),
  ];
  const index = rows.length === 0 ? 0 : Math.min(active, rows.length - 1);

  useEffect(() => {
    if (!open) return;
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      searchUsers(q, ctrl.signal).then(
        users => setFound({ query: q, users, failed: false }),
        () => { if (!ctrl.signal.aborted) setFound({ query: q, users: [], failed: true }); },
      );
    }, q === '' ? 0 : SEARCH_DELAY_MS);
    return () => { clearTimeout(timer); ctrl.abort(); };
  }, [open, q]);

  // Focus stays in the input (only aria-activedescendant moves), so scroll the active row.
  useEffect(() => {
    if (open) document.getElementById(`${listId}-${index}`)?.scrollIntoView?.({ block: 'nearest' });
  }, [open, index, listId]);

  function openList() {
    if (open || disabled) return;
    setQuery('');
    setActive(Math.max(options.findIndex(([v]) => v === value), 0));
    setOpen(true);
  }

  function choose(next: string) {
    setOpen(false);
    setQuery('');
    if (next !== value) onChange(next);
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.nativeEvent.isComposing) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!open) { openList(); return; }
      if (rows.length) setActive((index + (e.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length);
    } else if (e.key === 'Enter') {
      // Swallowed while open: the picker usually sits in a form.
      if (!open) return;
      e.preventDefault();
      if (rows[index]) choose(rows[index][0]);
    } else if (e.key === 'Escape') {
      if (open) { e.preventDefault(); e.stopPropagation(); setOpen(false); }
    }
  }

  // Hover follows the pointer, not rows scrolling under a still cursor during keyboard moves.
  const onHover = (i: number) => (e: MouseEvent) => {
    if (e.movementX !== 0 || e.movementY !== 0) setActive(i);
  };
  const searching = open && !fresh;

  return (
    <div className="relative">
      <input
        id={id}
        role="combobox"
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-haspopup="listbox"
        aria-autocomplete="list"
        aria-activedescendant={open && rows.length ? `${listId}-${index}` : undefined}
        autoComplete="off"
        disabled={disabled}
        value={open ? query : current}
        placeholder={open ? current || 'Search people…' : 'Search people…'}
        onChange={e => { setQuery(e.target.value); setActive(0); }}
        onFocus={openList}
        onClick={openList}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
        className={className ?? 'box-border w-full rounded-md border border-sf-line-strong bg-sf-card px-3 py-2 text-sm text-sf-ink placeholder:text-sf-ink-dim disabled:opacity-60'}
      />
      {open && (
        // mousedown would blur the input (and close the list) before a row's click lands.
        <div onMouseDown={e => e.preventDefault()}
          className="absolute top-full right-0 left-0 z-40 mt-1 max-h-60 min-w-48 overflow-y-auto rounded-md border border-sf-line-strong bg-sf-raised p-1 shadow-lg">
          <ul id={listId} role="listbox" aria-label={ariaLabel ?? 'People'} className="m-0 list-none p-0">
            {rows.map(([v, label], i) => (
              <li key={v} id={`${listId}-${i}`} role="option" aria-selected={i === index}
                onMouseMove={onHover(i)} onClick={() => choose(v)}
                className={`cursor-pointer rounded px-2.5 py-1.5 text-sm ${taken.has(v) ? 'text-sf-ink-mute' : 'text-sf-ink'} ${v === value ? 'font-medium' : ''} ${i === index ? 'bg-sf-hover' : ''}`}>
                {label}
              </li>
            ))}
          </ul>
          {fresh && found.failed && <p className="m-0 px-2.5 py-1.5 text-xs text-sf-red-text">Couldn't search people. Type to try again.</p>}
          {rows.length === 0 && !(fresh && found.failed) && (
            <p className="m-0 px-2.5 py-1.5 text-xs text-sf-ink-dim">{searching ? 'Searching…' : 'No one matches'}</p>
          )}
        </div>
      )}
    </div>
  );
}
