/**
 * Calls to `/api/core/contacts`. People and organizations share every route shape, so most
 * helpers take the kind. Errors are `ApiError {status, detail}`: 404 missing, 403 not writable,
 * 409 conflict or a write to a merged id, 422 invalid.
 */
import { ApiError, del, fetchJson, patchJson, postJson } from '../api/client';
import type { ContactDetail, ContactKind, ContactRef, SearchHit } from './types';

const BASE = '/api/core/contacts';

export const KINDS = {
  person: { path: 'people', entityType: 'core.person', noun: 'person', title: 'People' },
  organization: { path: 'organizations', entityType: 'core.organization', noun: 'organization', title: 'Organizations' },
} as const satisfies Record<ContactKind, { path: string; entityType: string; noun: string; title: string }>;

export const PAGE_SIZE = 50;

/** The app page of a record (`/people/3`). */
export const pageOf = (kind: ContactKind, id: number) => `/${KINDS[kind].path}/${id}`;
export const recordUrl = (kind: ContactKind, id: number | string) => `${BASE}/${KINDS[kind].path}/${id}`;
export const duplicatesUrl = (kind: ContactKind) => `${BASE}/${KINDS[kind].path}/duplicates`;

export interface ListFilters {
  q?: string;
  archived?: boolean;
  tag?: string;
  organization_id?: number;
  page?: number;
}

/** GET /people or /organizations with only the filters that are set. */
export function listUrl(kind: ContactKind, f: ListFilters): string {
  const p = new URLSearchParams();
  if (f.q?.trim()) p.set('q', f.q.trim());
  if (f.archived) p.set('archived', 'true');
  if (f.tag?.trim()) p.set('tag', f.tag.trim());
  if (f.organization_id !== undefined && kind === 'person') p.set('organization_id', String(f.organization_id));
  p.set('page', String(f.page ?? 1));
  p.set('page_size', String(PAGE_SIZE));
  return `${BASE}/${KINDS[kind].path}?${p}`;
}

export type RecordInput = Record<string, string | string[] | number | null>;

export const createRecord = <T = ContactDetail>(kind: ContactKind, body: RecordInput) =>
  postJson<T>(`${BASE}/${KINDS[kind].path}`, body);
/** Only the fields sent change; null clears. */
export const updateRecord = <T = ContactDetail>(kind: ContactKind, id: number, body: RecordInput) =>
  patchJson<T>(recordUrl(kind, id), body);
/** DELETE archives (it never destroys) and answers with the detail. */
export const archiveRecord = <T = ContactDetail>(kind: ContactKind, id: number) => sendDelete<T>(recordUrl(kind, id));
export const restoreRecord = <T = ContactDetail>(kind: ContactKind, id: number) =>
  postJson<T>(`${recordUrl(kind, id)}/restore`);
/** Folds `sourceId` into `targetId`; the target survives. Returns the survivor's detail. */
export const mergeRecords = <T = ContactDetail>(kind: ContactKind, targetId: number, sourceId: number) =>
  postJson<T>(`${BASE}/${KINDS[kind].path}/merge`, { target_id: targetId, source_id: sourceId });

// simplification: the client's `del()` takes no body and is typed void, and DELETE /links needs
// a JSON body; this mirrors its 401 and error handling. Upgrade: an optional body on `del()`.
async function sendDelete<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'DELETE', credentials: 'same-origin',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401) {
    window.location.assign('/login');
    return new Promise<never>(() => {});
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      if (typeof j.detail === 'string' && j.detail) detail = j.detail;
    } catch { /* not JSON */ }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export interface LinkKey {
  person_id: number;
  organization_id: number;
  role: string;
}

export interface LinkFields {
  is_primary?: boolean;
  started_on?: string | null;
  ended_on?: string | null;
}

export const linkRecords = (key: LinkKey & LinkFields) => postJson(`${BASE}/links`, key);
export const updateLink = (key: LinkKey, fields: LinkFields & { new_role?: string }) =>
  patchJson(`${BASE}/links`, { ...key, ...fields });
export const unlinkRecords = (key: LinkKey) => sendDelete(`${BASE}/links`, key);

type Part = 'channels' | 'addresses';
/** Channel fields (kind, value, label) or address fields (kind, line1, …, country), plus is_primary. */
export type PartInput = Record<string, string | boolean | null>;

export const addPart = (part: Part, ownerType: ContactKind, ownerId: number, body: PartInput) =>
  postJson(`${BASE}/${part}`, { owner_type: ownerType, owner_id: ownerId, ...body });
export const updatePart = (part: Part, id: number, body: PartInput) => patchJson(`${BASE}/${part}/${id}`, body);
export const deletePart = (part: Part, id: number) => del(`${BASE}/${part}/${id}`);

// ── The picker contract (lifted from CakeCRM dealLinkPickers.ts) ──────────────────────────────
// Module scope, and it must stay there: ContactPicker lists `search` in an effect's dependencies.

export const PICKER_LIMIT = 20;

export const searchContacts = (kind: ContactKind, q: string): Promise<SearchHit[]> =>
  q ? fetchJson<SearchHit[]>(`${BASE}/search?${new URLSearchParams({ q, kind, limit: String(PICKER_LIMIT) })}`) : Promise.resolve([]);

/**
 * Quick-create from a typed name. An organization name is unique among live records, so a 409
 * names the holder ("organization #12 already has that name"): link to it instead of failing,
 * as the donor's get-or-create did.
 */
export async function createContact(kind: ContactKind, name: string): Promise<ContactRef> {
  try {
    const rec = await createRecord<{ id: number; name: string }>(kind, { name });
    return { id: rec.id, name: rec.name };
  } catch (err) {
    const holder = err instanceof ApiError && err.status === 409 ? /#(\d+)/.exec(err.detail)?.[1] : undefined;
    if (!holder) throw err;
    const rec = await fetchJson<{ id: number; name: string }>(recordUrl(kind, holder));
    return { id: rec.id, name: rec.name };
  }
}

/** "a, b ,, c" -> ['a', 'b', 'c'] */
export const splitTags = (text: string) => text.split(',').map(t => t.trim()).filter(Boolean);

/** A user-facing message for a failed write. */
export function errorText(err: unknown, fallback: string): string {
  if (!(err instanceof ApiError)) return fallback;
  if (err.status === 403) return "You can't change this record.";
  if (err.status === 404) return 'That record no longer exists.';
  return err.detail && err.detail !== 'Unprocessable Entity' ? `${fallback} ${err.detail}` : fallback;
}
