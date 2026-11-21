import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, mockFetch, type Reply } from '../../testing';
import UsageCard from './UsageCard';

const SETTINGS = '/api/core/settings';
const RATE = { input: 4, output: 20, cache_read: 0.2, cache_write: 5 };
const row = (model: string, cost: number, unpriced = 0) => ({
  source: 'chat',
  model,
  calls: 3,
  input_tokens: 1000,
  output_tokens: 200,
  cache_read: 500,
  cache_write: 0,
  cost_micros: cost,
  unpriced,
});

afterEach(() => vi.unstubAllGlobals());

function renderCard() {
  const routes: Record<string, Reply> = {
    'GET /api/agent/usage': {
      body: {
        month: '2026-11',
        rows: [row('claude-opus-5-5', 1_234_500), row('new-model', 0, 3)],
        cost_micros: 1_234_500,
        cache_hit_rate: 0.25,
      },
    },
    [`GET ${SETTINGS}`]: {
      body: { values: { 'agent.cost_rates': { 'claude-opus-5-5': RATE } }, defaults: {}, secrets: {} },
    },
    [`PUT ${SETTINGS}`]: {
      body: { values: { 'agent.cost_rates': { 'claude-opus-5-5': { ...RATE, input: 3 } } }, defaults: {}, secrets: {} },
    },
  };
  const fetchMock = mockFetch(routes);
  render(<UsageCard />);
  return fetchMock;
}

describe('UsageCard', () => {
  it('shows the month total, the cache hit rate and the calls with no rate', async () => {
    renderCard();
    expect((await screen.findByTestId('usage-total')).textContent).toBe('$1.23');
    expect(screen.getByText(/Estimated spend for 2026-11, 25% of input read from the cache/)).toBeTruthy();
    expect(screen.getByText('no rate')).toBeTruthy();
    expect(screen.getByText(/3 calls ran on a model with no rate and are not in the total/)).toBeTruthy();
  });

  it('saves an edited rate and leaves an untouched unpriced model unpriced', async () => {
    const fetchMock = renderCard();
    fireEvent.change(await screen.findByLabelText('claude-opus-5-5 Input'), { target: { value: '3' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save rates' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', SETTINGS)).toHaveLength(1));
    const body = JSON.parse(callsTo(fetchMock, 'PUT', SETTINGS)[0][1]!.body as string);
    expect(body).toEqual({ values: { 'agent.cost_rates': { 'claude-opus-5-5': { ...RATE, input: 3 } } } });
  });
});
