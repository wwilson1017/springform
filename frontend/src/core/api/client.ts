/**
 * The API client. Auth is a session cookie (`credentials: 'same-origin'`), so nothing here
 * stores a token. Vite proxies /api to the backend in development.
 */

import createClient from 'openapi-fetch';
import type { paths } from './types.gen';

/**
 * A failed response, carrying the HTTP status so a caller can tell a REFUSAL (4xx: nothing was
 * written) from an UNKNOWN outcome (5xx or a dropped connection: it may have committed).
 */
export class ApiError extends Error {
  // Declared explicitly: `erasableSyntaxOnly` bans constructor parameter properties.
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(`API error ${status}: ${detail}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/** On these pages a 401 is an answer ("wrong password"), not an expired session. */
const AUTH_PAGES = ['/login', '/setup'];

/**
 * True when it navigated away. Outside the auth pages a 401 means the session is gone, so the
 * page goes to /login.
 */
function redirectOn401(status: number): boolean {
  if (status !== 401 || AUTH_PAGES.includes(window.location.pathname)) return false;
  window.location.assign('/login');
  return true;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, { credentials: 'same-origin', ...init });
  // Never settle: the page is navigating away, and throwing would flash every caller's
  // "Couldn't save" state in the instant before it does.
  if (redirectOn401(res.status)) return new Promise<never>(() => {});
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      // Only a string: FastAPI sends an ARRAY for a 422, and `detail` must stay a string.
      if (typeof body.detail === 'string' && body.detail) detail = body.detail;
    } catch { /* not JSON */ }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export const fetchJson = <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal });
export const postJson = <T>(path: string, body?: unknown) => send<T>('POST', path, body);
export const patchJson = <T>(path: string, body: unknown) => send<T>('PATCH', path, body);
export const del = (path: string) => request<void>(path, { method: 'DELETE' });
/** Multipart POST; the browser sets the boundary, so no Content-Type header here. */
export const upload = <T>(path: string, form: FormData) => request<T>(path, { method: 'POST', body: form });

/**
 * The typed client over the generated OpenAPI `paths` (`api.GET('/api/todos/...')`). It returns
 * `{ data, error }` rather than throwing, and shares the 401 redirect above.
 */
export const api = createClient<paths>({ credentials: 'same-origin' });
api.use({ onResponse: ({ response }) => { redirectOn401(response.status); } });
