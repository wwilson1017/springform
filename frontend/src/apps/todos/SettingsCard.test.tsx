// Settings → Todos: everyone reads the default visibility (from /filters, which members can
// read), and only an admin is offered the change, which goes through PUT /api/core/settings.
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider } from '../../core/auth/AuthContext';
import TodosSettingsCard from './SettingsCard';
import { filtersOf } from './testFixtures';

const user = (role: 'admin' | 'member') => ({ id: 1, email: 'ann@example.com', name: 'Ann', role, tz: 'UTC' });

/** fetch for the card: /api/me, /filters, and the settings PUT (a Request from openapi-fetch). */
function stub(role: 'admin' | 'member') {
  const puts: unknown[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(new URL(String(input), 'http://localhost'), init);
    const path = new URL(req.url).pathname;
    if (path === '/api/me') return new Response(JSON.stringify(user(role)));
    if (path === '/api/todos/filters') return new Response(JSON.stringify(filtersOf()));
    if (path === '/api/core/settings' && req.method === 'PUT') {
      puts.push(await req.json());
      return new Response(JSON.stringify({ values: {}, secrets: {}, defaults: {} }), { headers: { 'Content-Type': 'application/json' } });
    }
    return new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 });
  }));
  return puts;
}

afterEach(() => { vi.unstubAllGlobals(); });

describe('the Todos settings card', () => {
  it('tells a member the default and that an admin sets it', async () => {
    stub('member');
    render(<AuthProvider><TodosSettingsCard /></AuthProvider>);
    expect(await screen.findByText('Only the person who adds it')).toBeTruthy();
    expect(screen.getByText('An admin can change this.')).toBeTruthy();
    expect(screen.queryByRole('radio')).toBeNull();
  });

  it('lets an admin make new todos the whole team’s', async () => {
    const puts = stub('admin');
    render(<AuthProvider><TodosSettingsCard /></AuthProvider>);
    const team = await screen.findByRole('radio', { name: 'The whole team' });
    await waitFor(() => expect(team.getAttribute('aria-checked')).toBe('false'));
    fireEvent.click(team);
    await waitFor(() => expect(puts).toEqual([{ values: { 'todos.default_visibility': 'team' } }]));
    await waitFor(() => expect(team.getAttribute('aria-checked')).toBe('true'));
    expect(screen.getByText(/visible to:/).textContent).toContain('The whole team');
  });
});
