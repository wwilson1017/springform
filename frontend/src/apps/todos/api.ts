// The Todos API (/api/todos) on the core client: the session cookie says who is asking, and
// every refusal arrives as an ApiError carrying the service's own sentence (errors.ts).
import { del, fetchJson, patchJson, postJson } from '../../core/api/client';
import type {
  AreaIn, AreaPatch, Changes, ItemIn, ItemPatch, ProjectIn, ProjectPatch, Review, ReviewStatus,
  Todo, TodoArea, TodoFilters, TodoProject, TodoStatus, Visibility,
} from './types';

export const API = '/api/todos';

const qs = (params: object) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : '';
};

export interface TodoListParams {
  status?: TodoStatus;
  project_id?: number;
  /** Matches the area a todo SHOWS under: its own, else its project's. */
  area_id?: number;
  context?: string;
  tag?: string;
  person?: string;
  starred?: boolean;
  due_before?: string;
  due_after?: string;
  search?: string;
  assignee_user_id?: number;
  visibility?: Visibility;
  /** Only the caller's work: their private todos, team todos assigned to them, unassigned team todos. */
  mine?: boolean;
  limit?: number;
  /** Keep todos waiting on a future revisit date. Record views and project-health checks only:
   *  the working lists leave them out until their day. */
  include_deferred?: boolean;
}

/** The server's largest page: `limit` is capped there (router.py). */
const PAGE = 500;

/** Todos that match. An open list comes back WHOLE, however long: the server answers at most 500
 * rows at a time, so this pages by `offset` until a short page comes back. Every ordering there
 * ends in the id, so paging an unchanged list neither skips nor repeats a row. Done and Dropped,
 * which grow forever and show the newest, and a search stay ONE window of `limit` rows.
 *
 * simplification: a row filed or added between two pages can be skipped or repeated until the
 * next reload; paging by a key (after the last id) is the way up. */
export async function listTodos(params: TodoListParams = {}): Promise<Todo[]> {
  if (params.status === 'done' || params.status === 'dropped' || params.search) {
    return todoPage(params);
  }
  const all: Todo[] = [];
  for (;;) {
    const page = await todoPage({ ...params, limit: PAGE, offset: all.length });
    all.push(...page);
    if (page.length < PAGE) return all;
  }
}

const todoPage = (params: TodoListParams & { offset?: number }) => fetchJson<Todo[]>(`${API}/items${qs(params)}`);

export const getTodo = (id: number) => fetchJson<Todo>(`${API}/items/${id}`);
export const todayTodos = () => fetchJson<Todo[]>(`${API}/today`);
export const createTodo = (body: ItemIn) => postJson<Todo>(`${API}/items`, body);
export const updateTodo = (id: number, fields: ItemPatch) => patchJson<Todo>(`${API}/items/${id}`, fields);
/** Mark done; a repeating todo spawns its next occurrence. */
export const completeTodo = (id: number) => postJson<Todo>(`${API}/items/${id}/complete`);
/** For good: the owner's or an admin's call. Archiving is status 'dropped'. */
export const deleteTodo = (id: number) => del(`${API}/items/${id}`);

/** Team todos and the caller's private ones linked to a record. */
export const todosForRecord = (entityType: string, entityId: number, includeDone = false) =>
  fetchJson<Todo[]>(`${API}/for/${encodeURIComponent(entityType)}/${entityId}${qs({ include_done: includeDone || undefined })}`);

/** Rename a context on every todo carrying it. 409 = `next` already exists; resend with `merge`
 *  once the user has confirmed. */
export const renameContext = (old: string, next: string, merge = false) =>
  postJson<{ old: string; new: string; updated: number; merged: boolean }>(`${API}/contexts/rename`, { old, new: next, merge });

export const listProjects = (status?: string) => fetchJson<TodoProject[]>(`${API}/projects${qs({ status })}`);
export const getProject = (id: number) => fetchJson<TodoProject>(`${API}/projects/${id}`);
export const createProject = (body: ProjectIn) => postJson<TodoProject>(`${API}/projects`, body);
export const updateProject = (id: number, fields: ProjectPatch) => patchJson<TodoProject>(`${API}/projects/${id}`, fields);
export const deleteProject = (id: number) => del(`${API}/projects/${id}`);

/** The id of the project named `name` (any case) among those the user can see, creating it when
 *  there is none: how a typed project name (quick add's `#Project`, the edit sheet's "+ New
 *  project") becomes the `project_id` the API takes. */
export async function projectIdFor(name: string, known: TodoProject[], fields: Omit<ProjectIn, 'name'> = {}): Promise<number> {
  const hit = known.find(p => p.name.toLowerCase() === name.toLowerCase());
  return hit ? hit.id : (await createProject({ name, ...fields })).id;
}

/** Every area, archived ones included (the Areas page restores from them). */
export const listAreas = () => fetchJson<TodoArea[]>(`${API}/areas`);
export const createArea = (body: AreaIn) => postJson<TodoArea>(`${API}/areas`, body);
export const updateArea = (id: number, fields: AreaPatch) => patchJson<TodoArea>(`${API}/areas/${id}`, fields);
export const deleteArea = (id: number) => del(`${API}/areas/${id}`);

export const getFilters = () => fetchJson<TodoFilters>(`${API}/filters`);

export type { ReviewStatus };
/** The weekly review's data; its status half (review_due, days_since_review) is all the Review
 *  page reads, since it builds its sections from the lists. */
export const getReviewStatus = (): Promise<ReviewStatus> => fetchJson<Review>(`${API}/review`);
export const markReviewDone = () => postJson<ReviewStatus>(`${API}/review/done`);

/** What changed for this user after `sinceRev` (sync.ts). */
export const getChanges = (sinceRev: number) => fetchJson<Changes>(`${API}/changes${qs({ since_rev: sinceRev })}`);
