// Test fixtures: the server fields most donor tests never look at, so a fixture states only what
// it is about. Imported by tests only.
import type { Todo, TodoArea, TodoFilters, TodoProject } from './types';

export const OWNER = 1;

/** A private todo of user 1, unlinked, never synced: everything but the fields a test sets. */
export const ITEM_EXTRA = {
  people: [], area_id: null, effective_area_id: null, area_name: null, revisit_on: null,
  owner_user_id: OWNER, owner_name: 'Ann Owner', visibility: 'private', assignee_user_id: null,
  assignee_name: null, entity_type: null, entity_id: null, rev: 1,
} satisfies Partial<Todo>;

export const PROJECT_EXTRA = {
  purpose: '', outcome: '', area_id: null, area_name: null, owner_user_id: OWNER,
  visibility: 'private', assignee_user_id: null, rev: 1,
} satisfies Partial<TodoProject>;

export const AREA_EXTRA = {
  owner_user_id: OWNER, visibility: 'private', assignee_user_id: null, rev: 1,
} satisfies Partial<TodoArea>;

/** A whole filters payload: no contexts, no counts, two members, the browser's time zone. */
export const filtersOf = (over: Partial<TodoFilters> = {}): TodoFilters => ({
  contexts: [], tags: [], people: [], areas: [], status_counts: {}, tz: '',
  members: [{ id: OWNER, name: 'Ann Owner' }, { id: 2, name: 'Bo Member' }],
  default_visibility: 'private', ...over,
});
