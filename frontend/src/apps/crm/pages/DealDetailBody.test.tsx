import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, mockFetch, type Reply } from '../../../testing';
import { ymd } from '../closedOn';
import { deal, detail } from '../crm.testutil';
import type { DealDetail } from '../api';
import { DealDetailPage } from './DealDetailBody';

afterEach(() => vi.unstubAllGlobals());

const URL = '/api/crm/deals/7';

function setup(d: DealDetail, extra: Record<string, Reply> = {}) {
  const fetchMock = mockFetch({
    [`GET ${URL}`]: { body: d },
    [`GET ${URL}/health`]: { body: { deal: d, score: null, factors: {}, stale_days: 14, flags: [] } },
    [`GET ${URL}/touch-evidence`]: { body: { deal_id: 7, count: null, computed_at: null, current: true, items: [] } },
    'GET /api/core/timeline/mentionable': { body: [] },
    'GET /api/core/timeline?entity_type=crm.deal&entity_id=7&limit=50': { body: [] },
    'GET /api/core/files?entity_type=crm.deal&entity_id=7': { body: [] },
    ...extra,
  });
  render(
    <MemoryRouter initialEntries={['/crm/deals/7']}>
      <Routes><Route path="/crm/deals/:id" element={<DealDetailPage />} /></Routes>
    </MemoryRouter>,
  );
  return fetchMock;
}

const body = (fetchMock: ReturnType<typeof mockFetch>, method: string, url: string) =>
  JSON.parse(callsTo(fetchMock, method, url)[0][1]!.body as string);

describe('deal page stage controls', () => {
  it('marks the current stage and moves the deal with a PATCH of the stage alone', async () => {
    const d = detail({ id: 7, title: 'Spring order', stage: 'qualified' });
    const fetchMock = setup(d, { [`PATCH ${URL}`]: { body: deal({ ...d, stage: 'proposal' }) } });
    const group = await screen.findByRole('group', { name: 'Stage' });
    const current = within(group).getByRole('button', { name: 'Qualified' });
    expect(current.getAttribute('aria-pressed')).toBe('true');
    expect((current as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(group).getByRole('button', { name: 'Proposal' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'PATCH', URL)).toHaveLength(1));
    expect(body(fetchMock, 'PATCH', URL)).toEqual({ stage: 'proposal' });
  });

  it('Mark won asks the closing day (today by default) and posts it', async () => {
    const d = detail({ id: 7, title: 'Spring order', stage: 'negotiation' });
    const fetchMock = setup(d, { [`POST ${URL}/won`]: { body: deal({ ...d, stage: 'won', status: 'won' }) } });
    fireEvent.click(await screen.findByRole('button', { name: 'Mark won' }));
    const dialog = screen.getByRole('dialog', { name: 'When did this close?' });
    expect((within(dialog).getByLabelText('Closed on') as HTMLInputElement).value).toBe(ymd(new Date()));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Mark won' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', `${URL}/won`)).toHaveLength(1));
    expect(body(fetchMock, 'POST', `${URL}/won`)).toEqual({ closed_on: ymd(new Date()) });
  });

  it('refuses a future closing day without sending anything', async () => {
    const fetchMock = setup(detail({ id: 7, stage: 'proposal' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Mark won' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Closed on'), { target: { value: '2999-01-01' } });
    expect(within(dialog).getByRole('alert').textContent).toMatch(/future/);
    expect((within(dialog).getByRole('button', { name: 'Mark won' }) as HTMLButtonElement).disabled).toBe(true);
    expect(callsTo(fetchMock, 'POST', `${URL}/won`)).toHaveLength(0);
  });

  it('Mark lost posts the typed reason', async () => {
    const d = detail({ id: 7, stage: 'proposal' });
    const fetchMock = setup(d, { [`POST ${URL}/lost`]: { body: deal({ ...d, stage: 'lost', status: 'lost' }) } });
    fireEvent.click(await screen.findByRole('button', { name: 'Mark lost' }));
    const dialog = screen.getByRole('dialog', { name: 'Mark as lost' });
    fireEvent.change(within(dialog).getByLabelText('Reason (optional)'), { target: { value: ' Chose a competitor ' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Mark lost' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', `${URL}/lost`)).toHaveLength(1));
    expect(body(fetchMock, 'POST', `${URL}/lost`)).toEqual({ reason: 'Chose a competitor' });
  });

  it('Archive needs a reason; an archived deal offers Restore and no stage controls', async () => {
    const live = detail({ id: 7, stage: 'lead' });
    const fetchMock = setup(live, { [`POST ${URL}/archive`]: { body: deal({ ...live, archived_at: '2026-10-24T10:00:00Z' }) } });
    fireEvent.click(await screen.findByRole('button', { name: 'Archive' }));
    const dialog = screen.getByRole('dialog', { name: 'Archive deal' });
    const confirm = within(dialog).getByRole('button', { name: 'Archive' }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.change(within(dialog).getByLabelText('Why archive? (required)'), { target: { value: 'Entered twice' } });
    fireEvent.click(confirm);
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', `${URL}/archive`)).toHaveLength(1));
    expect(body(fetchMock, 'POST', `${URL}/archive`)).toEqual({ reason: 'Entered twice' });
  });

  it('shows an archived deal read-only with Restore', async () => {
    const d = detail({ id: 7, archived_at: '2026-10-24T10:00:00Z', archived_reason: 'Entered twice' });
    const fetchMock = setup(d, { [`POST ${URL}/restore`]: { body: deal({ ...d, archived_at: null }) } });
    expect(await screen.findByText(/Entered twice/)).toBeTruthy();
    expect(screen.queryByRole('group', { name: 'Stage' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Restore' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'POST', `${URL}/restore`)).toHaveLength(1));
  });

  it('saves only the changed fields, with money in cents', async () => {
    const d = detail({ id: 7, value_cents: 480_000, expected_close: null });
    const fetchMock = setup(d, { [`PATCH ${URL}`]: { body: deal({ ...d, value_cents: 525_050 }) } });
    fireEvent.change(await screen.findByLabelText('Value'), { target: { value: '5,250.50' } });
    fireEvent.change(screen.getByLabelText('Expected close'), { target: { value: '2026-12-01' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await vi.waitFor(() => expect(callsTo(fetchMock, 'PATCH', URL)).toHaveLength(1));
    expect(body(fetchMock, 'PATCH', URL)).toEqual({ value_cents: 525_050, expected_close: '2026-12-01' });
  });
});
