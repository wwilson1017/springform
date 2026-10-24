/**
 * Add or remove `value` in a multi-select facet's selection, returning a new array —
 * so a page wiring several facets writes `onToggle` without re-deriving the toggle.
 */
export function toggleValue<T>(list: readonly T[], value: T): T[] {
  return list.includes(value) ? list.filter(v => v !== value) : [...list, value];
}
