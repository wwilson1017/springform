import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, del, fetchJson, postJson } from './client';

function stub(status: number, body?: unknown, pathname = '/example') {
  const assign = vi.fn();
  vi.stubGlobal('location', { pathname, assign });
  const fetchMock = vi.fn(async () => new Response(
    body === undefined ? null : JSON.stringify(body), { status },
  ));
  vi.stubGlobal('fetch', fetchMock);
  return { assign, fetchMock };
}

afterEach(() => vi.unstubAllGlobals());

describe('client', () => {
  it('sends the session cookie and parses JSON', async () => {
    const { fetchMock } = stub(200, { id: 1 });
    expect(await postJson('/api/example/widgets', { name: 'a' })).toEqual({ id: 1 });
    expect(fetchMock).toHaveBeenCalledWith('/api/example/widgets', expect.objectContaining({
      credentials: 'same-origin', method: 'POST', body: '{"name":"a"}',
    }));
  });

  it('redirects a 401 to /login and never settles', async () => {
    const { assign } = stub(401, { detail: 'not_signed_in' });
    const settled = vi.fn();
    fetchJson('/api/example/widgets').then(settled, settled);
    await vi.waitFor(() => expect(assign).toHaveBeenCalledWith('/login'));
    await new Promise(r => setTimeout(r, 10));
    expect(settled).not.toHaveBeenCalled();
  });

  it('on the login page a 401 is an ApiError, not a redirect', async () => {
    const { assign } = stub(401, { detail: 'invalid_credentials' }, '/login');
    await expect(postJson('/api/auth/login', {})).rejects.toMatchObject({ status: 401, detail: 'invalid_credentials' });
    expect(assign).not.toHaveBeenCalled();
  });

  it('keeps detail a string when FastAPI sends a 422 array, and maps 204 to undefined', async () => {
    stub(422, { detail: [{ msg: 'field required' }] });
    const err = await fetchJson('/api/x').catch(e => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(typeof err.detail).toBe('string');
    stub(204);
    expect(await del('/api/core/files/1')).toBeUndefined();
  });
});
