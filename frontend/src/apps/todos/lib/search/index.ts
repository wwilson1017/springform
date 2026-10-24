/**
 * Shared search / filter bar — keyword search and facet filters for the client-side lists.
 *
 * The contract: the **page** owns the query and the facet selections; `SearchFilterBar` is
 * fully controlled; the page computes ONE filtered array and renders from it.
 *
 * Ported from cake-os `shared/search` without its tokenized matcher and sort helpers, which
 * nothing here uses (the pages filter with `util.matchesFilter`).
 */
export { default as SearchFilterBar } from './SearchFilterBar';
export { toggleValue } from './persist';
export type { FacetOption, FacetGroup, SortDir, SortState, SortFieldDef } from './types';
