import { useState, type ReactNode } from 'react';
import { SlidersHorizontal, ChevronDown, X } from './icons';
import SearchInput from './SearchInput';
import SortControl from './SortControl';
import type { FacetGroup, FacetOption, SortState } from './types';

/**
 * The shared search / filter / sort bar (ported from cake-os `shared/search`).
 *
 * ## What it is
 *
 * One row of chrome — keyword box, facet disclosure, sort control, result count, clear-all —
 * that every client-side list renders instead of hand-rolling its own.
 *
 * ## State ownership — the contract
 *
 * The bar is **fully controlled and owns nothing** except which disclosure panels are open.
 * Query text, facet selections and sort all live in the PAGE, which computes ONE filtered
 * array that it renders from.
 *
 * ## Facet groups are data, app-specific controls are slots
 *
 * `groups` covers the facets that are genuinely uniform: pick some values from a list. A
 * single-select facet is just a group whose `onToggle` replaces-or-clears, so the bar needs one
 * facet concept rather than two. Anything shaped differently goes in a slot — `extraFacets` for
 * a custom row inside the panel and `trailing` for a control that belongs in the top row.
 *
 * ## Active filters stay visible when the panel is closed
 *
 * The selected values render as removable chips in the bar itself, not only inside the
 * disclosure. A collapsed `Filters (3)` badge over an apparently-empty list tells a user that
 * something is filtered but not what.
 *
 * A selected value with no matching option still renders, labelled by its raw value. A chip
 * that silently disappears because its option went away looks exactly like a bug, and leaves
 * the user filtered by something they cannot see or clear.
 */

interface Props {
  query: string;
  onQueryChange: (value: string) => void;
  placeholder?: string;
  searchLabel?: string;

  groups?: FacetGroup[];
  /** Custom controls rendered inside the disclosure panel, below the groups. */
  extraFacets?: ReactNode;
  /**
   * The collapsed-row representation of whatever `extraFacets` renders.
   *
   * Required in spirit whenever `extraFacets` can constrain results: the chip row below can
   * only speak for `groups`, so without this a custom facet is counted in
   * `activeFacetCount` while being completely invisible until the panel is opened — which is
   * the "filtered but you cannot tell by what" failure this bar exists to prevent.
   */
  extraChips?: ReactNode;

  sort?: {
    /** Pass the app's `SortFieldDef[]` table directly — see `SortControl`. */
    options: readonly { value: string; label: string }[];
    value: SortState;
    defaultSort: SortState;
    onChange: (next: SortState) => void;
    /** Not the resting order — see `SortControl`'s `active` prop for why this is passed in. */
    active: boolean;
    note?: string;
    /** Accessible name for the field select, e.g. "Sort deals by". */
    ariaLabel?: string;
  };

  /** Rendered as "N of M" whenever both are supplied — unconditionally, not only while filtering. */
  visibleCount?: number;
  totalCount?: number;
  /** What the counts are counting, e.g. "cards" — "2258 of 2258" alone is hard to read. */
  countNoun?: string;
  /** Trailing note on the count line, e.g. the collection layer's "· column moves only" while a
   *  filtered board allows stage changes but not reordering (#3078). Sibling of `sort.note`. */
  countNote?: string;

  /** Whether anything is filtering right now (drives the Clear affordance). */
  active: boolean;
  /** How many facets are constraining results — shown on the disclosure button. */
  activeFacetCount: number;
  /** Reset every filter this bar represents. Scope is the app's to define and document. */
  onClear: () => void;
  /**
   * Bumped by the owner when it sets `query` PROGRAMMATICALLY, so the box re-adopts the value
   * even when the settled query did not change — see `SearchInput.resetNonce`. Clear already
   * does this internally; this is the same signal for a caller-driven set, which a value
   * comparison cannot see (#2845's saved views: applying a view whose query equals the
   * current one leaves half-typed text in the box, and its pending debounce then lands on
   * top of the view that was just applied).
   */
  externalResetNonce?: number;

  /** Controls rendered at the end of the top row. */
  trailing?: ReactNode;
}

export default function SearchFilterBar({
  query,
  onQueryChange,
  placeholder = 'Search...',
  searchLabel,
  groups = [],
  extraFacets,
  extraChips,
  sort,
  visibleCount,
  totalCount,
  countNoun,
  countNote,
  active,
  activeFacetCount,
  onClear,
  externalResetNonce = 0,
  trailing,
}: Props) {
  const [showFacets, setShowFacets] = useState(false);
  // Bumped on Clear so the search box empties even when the page's settled query was already
  // '' — see `SearchInput`'s `resetNonce`.
  const [resetNonce, setResetNonce] = useState(0);
  const hasPanel = groups.length > 0 || !!extraFacets;
  const showCount = visibleCount !== undefined && totalCount !== undefined;

  return (
    <div className="mb-4 flex flex-col gap-2">
      <div className="flex flex-col gap-2 md:flex-row md:flex-wrap md:items-center md:gap-3">
        <SearchInput
          value={query}
          onChange={onQueryChange}
          placeholder={placeholder}
          ariaLabel={searchLabel}
          // Either trigger resets the box. Summing two monotonic counters keeps one nonce
          // that only ever moves forwards, so neither source can mask the other.
          resetNonce={resetNonce + externalResetNonce}
          className="md:flex-1 md:max-w-sm"
        />

        {hasPanel && (
          <button
            type="button"
            onClick={() => setShowFacets(o => !o)}
            aria-expanded={showFacets}
            className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm border transition-colors shrink-0 ${
              activeFacetCount > 0
                ? 'bg-sf-accent text-sf-accent-ink border-sf-accent'
                : 'bg-sf-card text-sf-ink border-sf-line-strong hover:bg-sf-hover'
            }`}
          >
            <SlidersHorizontal className="w-4 h-4" aria-hidden="true" />
            Filters{activeFacetCount > 0 ? ` (${activeFacetCount})` : ''}
            <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showFacets ? 'rotate-180' : ''}`} aria-hidden="true" />
          </button>
        )}

        {sort && (
          <SortControl
            options={sort.options}
            value={sort.value}
            defaultSort={sort.defaultSort}
            onChange={sort.onChange}
            active={sort.active}
            note={sort.note}
            ariaLabel={sort.ariaLabel}
          />
        )}

        {showCount && (
          <span className="text-xs text-sf-ink-dim shrink-0">
            {visibleCount} of {totalCount}{countNoun ? ` ${countNoun}` : ''}{countNote ? ` ${countNote}` : ''}
          </span>
        )}

        {active && (
          <button
            type="button"
            onClick={() => { setResetNonce(n => n + 1); onClear(); }}
            className="text-xs text-sf-ink-dim hover:text-sf-ink underline shrink-0"
          >
            Clear filters
          </button>
        )}

        {trailing}
      </div>

      {!showFacets && (groups.some(g => g.selected.length > 0) || !!extraChips) && (
        <div className="flex flex-wrap items-center gap-1.5">
          {extraChips}
          {groups.flatMap(group =>
            group.selected.map(value => (
              <SelectedChip
                key={`${group.key}:${value}`}
                label={optionLabel(group.options, value)}
                groupLabel={group.label}
                onRemove={() => group.onToggle(value)}
              />
            )),
          )}
        </div>
      )}

      {showFacets && hasPanel && (
        <div className="p-3 bg-sf-card border border-sf-line-strong rounded-lg flex flex-col gap-3">
          {groups.map(group => <FacetRow key={group.key} group={group} />)}
          {extraFacets}
        </div>
      )}
    </div>
  );
}

/** A selected value's label, falling back to the raw value when no option matches it. */
function optionLabel(options: FacetOption[], value: string | number): string {
  return options.find(o => o.value === value)?.label ?? String(value);
}

export function ChipButton({
  label,
  active,
  onClick,
  title,
  color,
  disabled,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  title?: string;
  color?: string | null;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      disabled={disabled}
      aria-pressed={active}
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
        active
          ? 'bg-sf-accent text-sf-accent-ink border-sf-accent'
          : 'bg-sf-card text-sf-ink border-sf-line-strong hover:bg-sf-hover'
      }`}
    >
      {color && <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} />}
      {label}
    </button>
  );
}

function SelectedChip({ label, groupLabel, onRemove }: { label: string; groupLabel: string; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 pl-2.5 pr-1 py-1 bg-sf-bg text-sf-ink rounded-full text-xs">
      <span className="text-sf-ink-dim">{groupLabel}:</span>
      {label}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${groupLabel} filter ${label}`}
        className="w-4 h-4 inline-flex items-center justify-center rounded-full text-sf-ink-dim hover:text-sf-ink hover:bg-sf-hover"
      >
        <X className="w-3 h-3" aria-hidden="true" />
      </button>
    </span>
  );
}

/**
 * One facet group inside the disclosure panel.
 *
 * A `'list'` group stays collapsed until opened and mounts its rows only then. Kanban's
 * supplier, location, tag and used-for facets each run to hundreds of values; rendering all
 * four expanded at once is a thousand-plus checkbox nodes on a warehouse tablet, which is
 * exactly why the bar this generalises opened one checklist at a time.
 */
function FacetRow({ group }: { group: FacetGroup }) {
  const [open, setOpen] = useState(false);
  const isList = group.display === 'list';
  const count = group.selected.length;

  if (isList) {
    return (
      <div>
        <button
          type="button"
          onClick={() => setOpen(o => !o)}
          aria-expanded={open}
          className="flex items-center gap-1.5 text-xs font-medium text-sf-ink hover:text-sf-accent-text transition-colors"
        >
          <ChevronDown className={`w-3.5 h-3.5 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
          {group.label}
          {count > 0 && <span className="text-sf-accent-text">({count})</span>}
        </button>
        {group.hint && <p className="mt-0.5 text-xs text-sf-ink-dim">{group.hint}</p>}
        {open && <CheckList group={group} />}
      </div>
    );
  }

  return (
    <div>
      <div className="text-xs font-medium text-sf-ink mb-1.5">
        {group.label}
        {count > 0 && <span className="ml-1 text-sf-accent-text">({count})</span>}
      </div>
      {group.hint && <p className="-mt-1 mb-1.5 text-xs text-sf-ink-dim">{group.hint}</p>}
      <div className="flex flex-wrap gap-1.5">
        {group.options.map(o => {
          const isSelected = group.selected.includes(o.value);
          // A SELECTED chip is never disabled — it must stay clickable so a filter that became
          // un-choosable (a Maintenance stage that was hidden/closed AFTER it was selected) can
          // always be undone. Only an unselected, disabled option is blocked. (#1560 P1-1)
          return (
            <ChipButton
              key={o.value}
              label={o.label}
              color={o.color}
              active={isSelected}
              disabled={o.disabled === true && !isSelected}
              title={o.disabled === true && !isSelected ? o.disabledReason : undefined}
              onClick={() => group.onToggle(o.value)}
            />
          );
        })}
        {group.selected
          .filter(v => !group.options.some(o => o.value === v))
          .map(v => (
            <ChipButton key={`orphan:${v}`} label={String(v)} active onClick={() => group.onToggle(v)} />
          ))}
      </div>
    </div>
  );
}

/** A searchable, scrollable checklist for a high-cardinality facet. */
function CheckList({ group }: { group: FacetGroup }) {
  const [filter, setFilter] = useState('');
  const needle = filter.trim().toLowerCase();
  // A selected value that is not in `options` (its row vanished from a degraded or partial
  // load) is prepended rather than dropped — otherwise the group reads "(1)" with nothing to
  // untick, which is the same invisible-filter trap the collapsed chip row exists to close.
  const orphans = group.selected
    .filter(v => !group.options.some(o => o.value === v))
    .map(v => ({ value: v, label: String(v) }));
  const all = [...orphans, ...group.options];
  const shown = needle ? all.filter(o => o.label.toLowerCase().includes(needle)) : all;

  return (
    <div className="mt-1.5">
      <input
        type="text"
        value={filter}
        onChange={e => setFilter(e.target.value)}
        placeholder={`Filter ${group.label.toLowerCase()}...`}
        aria-label={`Filter ${group.label} options`}
        className="w-full max-w-xs px-2 py-1 mb-1.5 bg-sf-card border border-sf-line-strong rounded text-xs text-sf-ink placeholder:text-sf-ink-dim focus:outline-none focus:ring-2 focus:ring-sf-accent/30"
      />
      <div className="max-h-56 overflow-y-auto space-y-0.5 pr-1">
        {shown.map(o => (
          <label key={o.value} className="flex items-center gap-2 px-2 py-1 rounded hover:bg-sf-hover cursor-pointer text-sm text-sf-ink">
            <input
              type="checkbox"
              checked={group.selected.includes(o.value)}
              onChange={() => group.onToggle(o.value)}
              className="accent-sf-accent"
            />
            <span className="truncate">{o.label}</span>
          </label>
        ))}
        {shown.length === 0 && <p className="px-2 py-1 text-xs text-sf-ink-dim">No matches</p>}
      </div>
    </div>
  );
}
