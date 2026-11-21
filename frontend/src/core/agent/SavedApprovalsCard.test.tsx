import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, mockFetch } from '../../testing';
import SavedApprovalsCard from './SavedApprovalsCard';

afterEach(() => vi.unstubAllGlobals());

const RULE = {
  id: 4,
  tool: 'example_create_widget',
  agent_slug: 'whisk',
  agent_name: 'Helper',
  created_at: '2026-11-20T10:00:00Z',
};

describe('SavedApprovalsCard', () => {
  it('lists the saved approvals and Remove voids one', async () => {
    const fetchMock = mockFetch({
      'GET /api/agent/approval-rules': { body: [RULE] },
      'DELETE /api/agent/approval-rules/4': { body: { voided: true } },
    });
    render(<SavedApprovalsCard />);
    expect(await screen.findByText('example_create_widget')).toBeTruthy();
    expect(screen.getByText(/With Helper/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/agent/approval-rules/4')).toHaveLength(1));
    await waitFor(() => expect(callsTo(fetchMock, 'GET', '/api/agent/approval-rules')).toHaveLength(2));
  });

  it('says how to add one when there are none', async () => {
    mockFetch({ 'GET /api/agent/approval-rules': { body: [] } });
    render(<SavedApprovalsCard />);
    expect(await screen.findByText(/No saved approvals/)).toBeTruthy();
  });
});
