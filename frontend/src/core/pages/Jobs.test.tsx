import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { dismissToast, getToasts } from '../../shared/toast';
import { callsTo, mockFetch, type Reply } from '../../testing';
import { JobsPage } from './Jobs';
import type { JobInfo } from './types';

const job: JobInfo = {
  name: 'core.requests_refresh', app: 'core', every: 900, at: null, timeout: 120,
  last_run: { status: 'error', started_at: '2026-10-24T03:00:00Z', finished_at: '2026-10-24T03:00:01Z', error: 'boom' },
  in_flight: false,
};
const RUN = '/api/core/jobs/core.requests_refresh/run';

function renderJobs(runReply: Reply, extra: Record<string, Reply> = {}) {
  const fetchMock = mockFetch({
    'GET /api/core/jobs': { body: [job] },
    'GET /api/core/jobs/runs?limit=20': { body: [] },
    'GET /api/core/jobs/outbox/dead?limit=50': { body: [] },
    [`POST ${RUN}`]: runReply,
    ...extra,
  });
  render(<JobsPage />);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  for (const t of getToasts()) dismissToast(t.id);
});

describe('JobsPage run now', () => {
  it.each([
    ['202 starts it', { status: 202, body: { started: true } }, 'success', 'Started core.requests_refresh.'],
    ['409 says it is already running', { status: 409, body: { detail: 'already_running' } }, 'info',
      'core.requests_refresh is already running; it was not started again.'],
    ['503 says the scheduler is down', { status: 503, body: { detail: 'scheduler_not_running' } }, 'error',
      "The scheduler isn't running on this server, so jobs can't be started now."],
  ] as const)('%s', async (_, reply, severity, message) => {
    const fetchMock = renderJobs(reply);
    expect(await screen.findByText('boom')).toBeTruthy(); // the last run's error shows on the row
    fireEvent.click(screen.getByRole('button', { name: 'Run now' }));
    await waitFor(() => expect(getToasts().map(t => [t.severity, t.message])).toEqual([[severity, message]]));
    expect(callsTo(fetchMock, 'POST', RUN)).toHaveLength(1);
  });

  it('filters the runs list to a job when its name is clicked', async () => {
    renderJobs({ status: 202 }, {
      'GET /api/core/jobs/runs?job=core.requests_refresh&limit=20': { body: [{
        id: 7, job: job.name, app: 'core', trigger: 'manual', status: 'ok', scheduled_for: null,
        started_at: '2026-10-24T03:00:00Z', finished_at: '2026-10-24T03:00:00Z', error: null,
      }] },
    });
    fireEvent.click(await screen.findByRole('button', { name: job.name }));
    expect(await screen.findByText('manual')).toBeTruthy();
  });
});
