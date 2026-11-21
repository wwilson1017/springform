import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, mockFetch, type Reply } from '../../testing';
import SkillsCard from './SkillsCard';
import type { Skill } from './types';

const SETTINGS = '/api/core/settings';
const list = (status: string, limit = 50) => `GET /api/core/skills?status=${status}&limit=${limit}`;
const skill = (over: Partial<Skill>): Skill => ({
  id: 7,
  name: 'weekly-count',
  description: 'Count the stock every Monday',
  body: '1. Count each shelf.',
  status: 'proposed',
  author: 'agent',
  author_name: null,
  pinned: false,
  use_count: 0,
  last_used_at: null,
  source_conversation_id: 12,
  revises_id: null,
  revises_name: null,
  created_at: '2026-11-20T09:00:00Z',
  updated_at: '2026-11-20T09:00:00Z',
  approved_at: null,
  approved_by: null,
  ...over,
});
const page = (skills: Skill[]) => ({ body: { skills, total: skills.length, last_review: null } });

afterEach(() => vi.unstubAllGlobals());

function renderCard() {
  const routes: Record<string, Reply> = {
    [list('proposed')]: page([skill({})]),
    [list('proposed', 1)]: {
      body: { skills: [], total: 1, last_review: { ran_at: '2026-11-20T10:00:00Z', status: 'ok', proposals: 1 } },
    },
    [list('active')]: page([
      skill({
        id: 8,
        name: 'pricing',
        status: 'active',
        author: '1',
        author_name: 'Admin',
        source_conversation_id: null,
      }),
    ]),
    [list('archived')]: page([]),
    [`GET ${SETTINGS}`]: { body: { values: { 'agent.skills_review_enabled': false }, defaults: {}, secrets: {} } },
    [`PUT ${SETTINGS}`]: { body: { values: { 'agent.skills_review_enabled': true }, defaults: {}, secrets: {} } },
    'POST /api/core/skills/7/approve': { body: skill({ status: 'active' }) },
    'POST /api/core/skills': { body: skill({ id: 9, status: 'active' }) },
  };
  const fetchMock = mockFetch(routes);
  render(<SkillsCard />);
  return fetchMock;
}

describe('SkillsCard', () => {
  it('shows a proposal with its source and approves it', async () => {
    const fetchMock = renderCard();
    expect(await screen.findByText('weekly-count')).toBeTruthy();
    expect(screen.getByText(/from conversation #12/)).toBeTruthy();
    expect(screen.getByText('1. Count each shelf.')).toBeTruthy(); // a proposal opens with its steps shown
    expect(screen.getByText(/Last review .*: 1 proposed\./)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/core/skills/7/approve')).toHaveLength(1));
    await waitFor(() => expect(callsTo(fetchMock, 'GET', '/api/core/skills?status=active&limit=50')).toHaveLength(2));
  });

  it('turns the review on', async () => {
    const fetchMock = renderCard();
    fireEvent.click(await screen.findByLabelText('Propose skills from conversations'));
    await waitFor(() => expect(callsTo(fetchMock, 'PUT', SETTINGS)).toHaveLength(1));
    const body = JSON.parse(callsTo(fetchMock, 'PUT', SETTINGS)[0][1]!.body as string);
    expect(body).toEqual({ values: { 'agent.skills_review_enabled': true } });
  });

  it('writes a skill by hand', async () => {
    const fetchMock = renderCard();
    await screen.findByText('pricing');
    const form = screen.getByRole('region', { name: 'New skill' });
    const inputs = form.querySelectorAll('input, textarea');
    fireEvent.change(inputs[0], { target: { value: 'open-up' } });
    fireEvent.change(inputs[1], { target: { value: 'Open the shop' } });
    fireEvent.change(inputs[2], { target: { value: '1. Unlock.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add skill' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/core/skills')).toHaveLength(1));
    const body = JSON.parse(callsTo(fetchMock, 'POST', '/api/core/skills')[0][1]!.body as string);
    expect(body).toEqual({ name: 'open-up', description: 'Open the shop', body: '1. Unlock.' });
  });
});
