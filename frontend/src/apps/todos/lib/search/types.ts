/** Shared search / filter types. */

/** One selectable value inside a facet group. */
export interface FacetOption {
  value: string | number;
  label: string;
  /** Optional swatch color. */
  color?: string | null;
  /**
   * Offered but not currently choosable (#1560: a Maintenance stage the board is not
   * rendering because it is hidden or closed). A SELECTED value is never actually disabled —
   * the bar keeps it clickable so a stale filter can always be undone (see `FacetRow`).
   */
  disabled?: boolean;
  /** Tooltip explaining why the option is disabled (e.g. "Turn on Show closed to filter this lane"). */
  disabledReason?: string;
}

/**
 * A multi-select facet. The app owns the selection state and the toggle behaviour; this is
 * purely how the bar is told what to draw.
 *
 * Single-select facets are expressed as a group whose `onToggle` replaces-or-clears rather
 * than accumulating — the bar does not need to know the difference.
 */
export interface FacetGroup {
  key: string;
  label: string;
  options: FacetOption[];
  selected: (string | number)[];
  onToggle: (value: string | number) => void;
  /** Short helper line under the group's options. */
  hint?: string;
  /**
   * `'chips'` (default) suits a small enumerable facet. `'list'` renders a searchable,
   * scrollable checklist and mounts its rows ONLY while that group is expanded — required
   * for high-cardinality facets (kanban's supplier and location lists run to hundreds of
   * values, and mounting four of them at once is a thousand-plus nodes on a warehouse
   * tablet).
   */
  display?: 'chips' | 'list';
}
