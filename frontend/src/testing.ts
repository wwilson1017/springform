import { vi } from 'vitest';

export interface Reply {
  status?: number;
  body?: unknown;
}

/**
 * Stub `fetch` with replies keyed by "METHOD url" (query string included). Anything unlisted
 * answers 404, so a test fails loudly on a request it did not expect to matter. Returns the mock
 * for call assertions.
 */
export function mockFetch(routes: Record<string, Reply>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const reply = routes[`${init?.method ?? 'GET'} ${url}`] ?? { status: 404, body: { detail: 'not_found' } };
    return new Response(reply.body === undefined ? null : JSON.stringify(reply.body), { status: reply.status ?? 200 });
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

/** The calls made to one "METHOD url". */
export const callsTo = (fn: ReturnType<typeof mockFetch>, method: string, url: string) =>
  fn.mock.calls.filter(([input, init]) => input === url && (init?.method ?? 'GET') === method);
