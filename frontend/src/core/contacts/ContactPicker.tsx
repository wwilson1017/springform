/**
 * Type-to-search picker for a person or an organization, with optional inline create. Any area
 * that points at the directory uses it:
 *
 *   <ContactPicker kind="organization" value={org} onChange={setOrg} allowCreate />
 *
 * Lifted from CakeCRM's generic RecordCombobox, specialised to GET /api/core/contacts/search.
 * The selected record's name comes from `value`, never from a page of results, so a linked
 * record outside any result page still shows. Keyboard: arrows move, Enter picks (only once the
 * user has typed or arrowed, so a reflexive Enter never replaces a link), Escape closes.
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react';
import { createContact, searchContacts } from './api';
import type { ContactKind, ContactRef, ContactSearchHit } from './types';
import { useDebounce } from './useDebounce';

export interface ContactPickerProps {
  kind: ContactKind;
  value: ContactRef | null;
  onChange: (value: ContactRef | null) => void;
  /** Offer `Create "<typed name>"` when nothing matches exactly. */
  allowCreate?: boolean;
  placeholder?: string;
  /** A visible label; without one the input is labelled by the placeholder. */
  label?: string;
  /** Ids never offered (the record itself, when merging it into another). */
  exclude?: number[];
}

export function ContactPicker({ kind, value, onChange, allowCreate, placeholder, label, exclude }: ContactPickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  // The last settled search, tagged with the query it answered, so rows are shown only for
  // the query on screen.
  const [settled, setSettled] = useState<{ query: string; rows: ContactSearchHit[]; failed: boolean } | null>(null);
  // The name the in-flight create was called with (the box stays editable meanwhile).
  const [creatingName, setCreatingName] = useState<string | null>(null);
  const creating = creatingName !== null;
  const [navigated, setNavigated] = useState(false);
  const [error, setError] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  // A slow earlier search must not overwrite a newer one.
  const reqRef = useRef(0);
  // Bumped by every choice and cancel, so a create that lands late knows it was superseded.
  const intentRef = useRef(0);
  const listId = useId();
  const inputId = `${listId}-input`;
  const debounced = useDebounce(query, 250);

  const trimmed = query.trim();
  const pending = debounced.trim();
  const fresh = settled !== null && settled.query === pending && pending === trimmed;
  const results = fresh ? settled.rows.filter(r => !exclude?.includes(r.id)) : [];
  const loading = open && trimmed !== '' && !fresh;
  // A failed search is not an empty one: saying "No matches" would invite a duplicate.
  const searchFailed = fresh && settled.failed;
  const exactMatch = results.some(r => r.name.trim().toLowerCase() === trimmed.toLowerCase());
  const canCreate = Boolean(allowCreate) && trimmed !== '' && !loading && !exactMatch;
  const showCreate = canCreate || creating;
  const createIndex = results.length;
  const rowCount = results.length + (showCreate ? 1 : 0);
  const active = rowCount === 0 ? 0 : Math.min(activeIndex, rowCount - 1);

  useEffect(() => {
    if (!open || debounced.trim() !== trimmed) return;
    const seq = ++reqRef.current;
    let cancelled = false;
    const q = debounced.trim();
    const land = (rows: ContactSearchHit[], failed: boolean) => {
      if (cancelled || seq !== reqRef.current) return;
      setSettled({ query: q, rows, failed });
      setActiveIndex(0);
    };
    searchContacts(kind, q).then(rows => land(rows, false), () => land([], true));
    return () => { cancelled = true; };
  }, [open, debounced, trimmed, kind]);

  // Focus never leaves the input (only aria-activedescendant moves), so scroll the active row.
  useEffect(() => {
    if (open) document.getElementById(`${listId}-${active}`)?.scrollIntoView?.({ block: 'nearest' });
  }, [open, active, listId]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: globalThis.MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  function openList() {
    if (open) return;
    setQuery('');
    setSettled(null);
    setError('');
    setNavigated(false);
    setActiveIndex(0);
    setOpen(true);
  }

  /** Close and abandon an in-flight create: an explicit "never mind". A click-away only closes. */
  function cancel() {
    intentRef.current++;
    setCreatingName(null);
    setOpen(false);
  }

  function choose(ref: ContactRef) {
    intentRef.current++;
    onChange({ id: ref.id, name: ref.name });
    setOpen(false);
    setQuery('');
    setError('');
  }

  function clearSelection() {
    intentRef.current++;
    setError('');
    onChange(null);
  }

  async function quickCreate() {
    if (!canCreate || creating) return;
    const intent = ++intentRef.current;
    setCreatingName(trimmed);
    setError('');
    try {
      const created = await createContact(kind, trimmed);
      if (intentRef.current === intent) choose(created);
    } catch (err) {
      if (intentRef.current === intent) setError(err instanceof Error ? err.message.replace(/^API error \d+: /, '') : "Couldn't create it");
    } finally {
      setCreatingName(null);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.nativeEvent.isComposing) return;
    if (e.key === 'Escape') {
      if (open) { e.preventDefault(); e.stopPropagation(); cancel(); }
      return;
    }
    if (e.key === 'Tab') {
      if (open) setOpen(false);
      return;
    }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!open) { openList(); return; }
      if (rowCount === 0) return;
      setNavigated(true);
      setActiveIndex((active + (e.key === 'ArrowDown' ? 1 : -1) + rowCount) % rowCount);
      return;
    }
    if (e.key === 'Enter') {
      // Always swallowed while open: the picker usually sits inside a form.
      if (!open) return;
      e.preventDefault();
      if (trimmed === '' && !navigated) { setOpen(false); return; }
      if (canCreate && active === createIndex) { void quickCreate(); return; }
      const hit = results[active];
      if (hit) choose(hit);
    }
  }

  // Hover follows the pointer, not rows scrolling under a still cursor during keyboard moves.
  const onRowHover = (i: number) => (e: MouseEvent) => {
    if (e.movementX !== 0 || e.movementY !== 0) setActiveIndex(i);
  };
  const row = 'block w-full cursor-pointer rounded px-2.5 py-1.5 text-left text-sm';
  const empty = placeholder ?? (kind === 'person' ? 'Search people…' : 'Search organizations…');

  return (
    <div ref={wrapRef} className="relative">
      {label && <label htmlFor={inputId} className="mb-1 block text-xs font-medium text-sf-ink-mute">{label}</label>}
      <div className="relative">
        <input
          id={inputId}
          role="combobox"
          aria-label={label ? undefined : empty}
          aria-expanded={open}
          aria-controls={open ? listId : undefined}
          aria-haspopup="listbox"
          aria-autocomplete="list"
          aria-activedescendant={open && rowCount > 0 ? `${listId}-${active}` : undefined}
          autoComplete="off"
          value={open ? query : value?.name ?? ''}
          placeholder={value?.name ?? empty}
          onChange={e => { intentRef.current++; setQuery(e.target.value); setError(''); }}
          onFocus={openList}
          onClick={openList}
          onKeyDown={onKeyDown}
          className={`w-full rounded-md border border-sf-line-strong bg-sf-card px-3 py-2 text-sm text-sf-ink placeholder:text-sf-ink-dim ${value ? 'pr-8' : ''}`}
        />
        {value && !open && (
          <button type="button" aria-label={`Clear ${label?.toLowerCase() ?? value.name}`} onClick={clearSelection}
            className="absolute top-1/2 right-1 -translate-y-1/2 cursor-pointer border-0 bg-transparent px-1.5 text-base leading-none text-sf-ink-dim">
            ×
          </button>
        )}
      </div>
      {error && <p className="mt-1 mb-0 text-xs text-sf-red-text">{error}</p>}
      {open && (
        <div className="absolute top-full right-0 left-0 z-40 mt-1 max-h-60 overflow-y-auto rounded-md border border-sf-line-strong bg-sf-raised p-1 shadow-lg">
          <ul id={listId} role="listbox" aria-label={label ?? empty} className="m-0 list-none p-0">
            {results.map((r, i) => (
              <li key={r.id} id={`${listId}-${i}`} role="option" aria-selected={i === active}
                onMouseMove={onRowHover(i)} onClick={() => choose(r)}
                className={`${row} text-sf-ink ${i === active ? 'bg-sf-hover' : ''}`}>
                <span className="block">{r.name}</span>
                {(r.email || r.phone) && <span className="block text-xs text-sf-ink-mute">{r.email || r.phone}</span>}
              </li>
            ))}
            {showCreate && (
              <li id={`${listId}-${createIndex}`} role="option" aria-selected={active === createIndex} aria-disabled={creating}
                onMouseMove={onRowHover(createIndex)} onClick={() => void quickCreate()}
                className={`${row} font-medium text-sf-accent-text ${active === createIndex ? 'bg-sf-hover' : ''} ${results.length ? 'rounded-none border-t border-sf-line-strong' : ''}`}>
                {creating ? `Creating "${creatingName}"…` : `Create "${trimmed}"…`}
              </li>
            )}
          </ul>
          {searchFailed && <p className="m-0 px-2.5 py-1.5 text-xs text-sf-red-text">Search failed; results may be incomplete.</p>}
          {rowCount === 0 && !searchFailed && (
            <p className="m-0 px-2.5 py-1.5 text-xs text-sf-ink-dim">
              {trimmed === '' ? 'Type to search' : loading ? 'Searching…' : 'No matches'}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
