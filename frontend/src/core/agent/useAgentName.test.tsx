import { act, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ExportCard from '../settings/ExportCard';
import nav from './nav';
import NightlyCard from './NightlyCard';
import { setAgentName } from './useAgentName';

afterEach(() => vi.unstubAllGlobals());

describe('the assistant name', () => {
  it('reaches the nav and the cards, and follows a rename', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/agent/status') return new Response(JSON.stringify({ name: 'Ada' }));
        if (url === '/api/core/settings') return new Response(JSON.stringify({ values: {} }));
        return new Response(JSON.stringify({ tables: [] }));
      }),
    );
    render(
      <MemoryRouter>
        <span data-testid="nav">{nav[0].label}</span>
        <ExportCard />
        <NightlyCard />
      </MemoryRouter>,
    );
    expect(await screen.findByText('Ada', { selector: '[data-testid=nav]' })).toBeTruthy();
    expect(await screen.findByText(/Ada conversations are never/)).toBeTruthy();
    expect(await screen.findByText(/At 02:00 Ada reads/)).toBeTruthy();

    act(() => setAgentName('Bo'));
    expect(screen.getByTestId('nav').textContent).toBe('Bo');
    expect(screen.getByText(/Bo conversations are never/)).toBeTruthy();
    expect(screen.getByText(/At 02:00 Bo reads/)).toBeTruthy();
  });
});
