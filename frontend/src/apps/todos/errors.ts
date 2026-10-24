import { ApiError } from '../../core/api/client';

export { ApiError };

/**
 * The server's own `detail` sentence when there is one (the todos service writes a readable
 * reason for every 403, 409 and 422), else the fallback. The core client keeps `detail` a string
 * and falls back to the status text ("Not Found"), so a bare status text is not shown as if it
 * were a reason. Any other error (offline) says what it is.
 */
export function apiErrorMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError) return e.detail && !/^[A-Z][a-z]+( [A-Z][a-z]+)*$/.test(e.detail) ? e.detail : fallback;
  return e instanceof Error && e.message ? e.message : fallback;
}
