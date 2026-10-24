/**
 * The context facet for the pages that filter by context (Inbox, Next Actions, Someday, Done).
 * They own their query/facet state and pass it to `SearchFilterBar` as fully-controlled
 * props; sharing the option-building and the match rule here keeps them from drifting.
 */
import type { FacetGroup, FacetOption } from './lib/search';

/**
 * Facet values are matched EXACTLY by the bar, while the `<select>` this replaces compared
 * case-insensitively (`util.matchesFilter`). So values are lower-cased on both sides and only
 * the label keeps the casing the user typed.
 *
 * One option per lower-cased value, first spelling wins. Contexts are free text, so the
 * server's list can hold `@home` AND `@Home`; both already match the same todos here, and
 * two options sharing one value would render two identical chips under one React key.
 */
export function contextOptions(contexts: string[]): FacetOption[] {
  const seen = new Set<string>();
  const options: FacetOption[] = [];
  for (const c of contexts) {
    const value = c.toLowerCase();
    if (seen.has(value)) continue;
    seen.add(value);
    options.push({ value, label: c });
  }
  return options;
}

export function contextGroup(
  contexts: string[],
  selected: (string | number)[],
  onToggle: (value: string | number) => void,
): FacetGroup {
  return { key: 'context', label: 'Context', options: contextOptions(contexts), selected, onToggle };
}

/** The people facet, beside contexts. Names are matched exactly, as the server's
 *  `person` filter does. */
export function peopleGroup(
  people: string[],
  selected: (string | number)[],
  onToggle: (value: string | number) => void,
): FacetGroup {
  return {
    key: 'people', label: 'People',
    options: people.map(p => ({ value: p, label: p })), selected, onToggle,
  };
}

/** Whether a todo passes the people facet: nothing selected means everyone, otherwise
 *  it must involve at least one selected person. */
export function matchesPeople(people: string[] | undefined, selected: (string | number)[]): boolean {
  return selected.length === 0 || (people ?? []).some(p => selected.includes(p));
}

/**
 * Whether a todo passes the context facet.
 *
 * Multi-select is a deliberate superset of the old single-select dropdown: an empty selection
 * means "all contexts" exactly as the blank option did, and selecting one behaves identically.
 * A todo with no context matches only when nothing is selected — the same as before, since the
 * dropdown had no "unfiled" option to choose.
 */
export function matchesContexts(context: string, selected: (string | number)[]): boolean {
  return selected.length === 0 || selected.includes(context.toLowerCase());
}
