import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider } from '../../../core/auth/AuthContext';
import { callsTo, mockFetch, type Reply } from '../../../testing';
import { deal } from '../crm.testutil';
import type { Deal } from '../api';
import { PipelinePage } from './PipelinePage';

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

const BOARD = '/api/crm/deals?limit_per_stage=200';
const deals = [
  deal({ id: 1, title: 'Spring order', stage: 'proposal', value_cents: 480_000 }),
  deal({ id: 2, title: 'Café subscription', stage: 'negotiation', value_cents: 1_250_000 }),
  deal({ id: 3, title: 'Shelf placement', stage: 'lead', value_cents: 900_000 }),
];

function setup(extra: Record<string, Reply> = {}, list: Deal[] = deals) {
  const fetchMock = mockFetch({
    'GET /api/me': { body: { id: 1, email: 'a@example.com', name: 'Ada Admin', role: 'admin', tz: 'UTC' } },
    'GET /api/core/timeline/mentionable': { body: [{ id: 1, name: 'Ada Admin' }] },
    'GET /api/crm/stage-criteria': { body: [] },
    [`GET ${BOARD}`]: { body: { deals: list, stage_summary: [], total_pipeline_value_cents: 0, deals_truncated: false } },
    ...extra,
  });
  render(<MemoryRouter><AuthProvider><PipelinePage /></AuthProvider></MemoryRouter>);
  return fetchMock;
}

const column = (name: RegExp) => screen.getByRole('region', { name });

describe('pipeline board', () => {
  it('renders each deal in its stage column with the column count and total', async () => {
    setup();
    await screen.findByText('Spring order');
    const proposal = column(/^Proposal: 1 deals/);
    expect(within(proposal).getByText('Spring order')).toBeTruthy();
    expect(within(proposal).getAllByText('$4,800').length).toBeGreaterThan(0);
    expect(screen.queryByRole('region', { name: /^Won/ })).toBeNull();
    expect(screen.getByText('$26,300')).toBeTruthy(); // open pipeline: 4,800 + 12,500 + 9,000
  });

  it('moves a deal with its Move menu: the card moves at once and the PATCH carries the stage', async () => {
    const fetchMock = setup({ 'PATCH /api/crm/deals/3': { body: { ...deals[2], stage: 'qualified' } } });
    fireEvent.change(await screen.findByLabelText('Move Shelf placement to'), { target: { value: 'qualified' } });
    expect(within(column(/^Qualified/)).getByText('Shelf placement')).toBeTruthy();
    await vi.waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/crm/deals/3')).toHaveLength(1));
    expect(JSON.parse(callsTo(fetchMock, 'PATCH', '/api/crm/deals/3')[0][1]!.body as string)).toEqual({ stage: 'qualified' });
  });

  it('puts the card back when the server refuses the move', async () => {
    setup({ 'PATCH /api/crm/deals/3': { status: 409, body: { detail: 'Deal #3 is archived; restore it before changing its stage' } } });
    fireEvent.change(await screen.findByLabelText('Move Shelf placement to'), { target: { value: 'qualified' } });
    await vi.waitFor(() => expect(within(column(/^Lead/)).getByText('Shelf placement')).toBeTruthy());
  });

  it('bulk-moves the selected deals in one request', async () => {
    const fetchMock = setup({ 'POST /api/crm/deals/bulk-move': { body: { ok: true, updated: 2, updated_ids: [1, 3], errors: [] } } });
    fireEvent.click(await screen.findByLabelText('Select Spring order'));
    fireEvent.click(screen.getByLabelText('Select Shelf placement'));
    const bar = screen.getByRole('region', { name: 'Bulk actions' });
    expect(within(bar).getByText('2 selected')).toBeTruthy();
    fireEvent.change(within(bar).getByLabelText('Move selected to'), { target: { value: 'negotiation' } });
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/crm/deals/bulk-move')).toHaveLength(1));
    expect(JSON.parse(callsTo(fetchMock, 'POST', '/api/crm/deals/bulk-move')[0][1]!.body as string)).toEqual({ ids: [1, 3], stage: 'negotiation' });
  });
});
