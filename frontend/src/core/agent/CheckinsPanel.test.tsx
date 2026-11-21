import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ConfirmHost } from '../../shared/ConfirmHost';
import { callsTo, mockFetch } from '../../testing';
import { describeSchedule, scheduleText } from './checkinSchedule';
import CheckinsPanel from './CheckinsPanel';
import type { Checkin } from './types';

afterEach(() => vi.unstubAllGlobals());

const CHECKIN: Checkin = {
  id: 3,
  name: 'Morning look',
  prompt: 'Anything overdue?',
  schedule: 'weekly:mon@09:00',
  enabled: true,
  next_run_at: '2026-11-23T15:00:00Z',
  failures: 0,
  last_run_at: '2026-11-16T15:00:00Z',
  last_status: 'silent',
  last_error: null,
  created_at: '2026-11-01T10:00:00Z',
};

describe('schedule text', () => {
  it('builds and describes the three kinds', () => {
    expect(scheduleText('every', 60, 'mon', '09:00')).toBe('every:60');
    expect(scheduleText('daily', 60, 'mon', '09:00')).toBe('daily@09:00');
    expect(scheduleText('weekly', 60, 'fri', '17:30')).toBe('weekly:fri@17:30');
    expect(describeSchedule('every:60')).toBe('Every 60 minutes');
    expect(describeSchedule('daily@09:00')).toBe('Daily at 09:00');
    expect(describeSchedule('weekly:fri@17:30')).toBe('Fridays at 17:30');
  });
});

describe('CheckinsPanel', () => {
  it('lists a check-in with its schedule and last result; Pause, Run now and Delete call the API', async () => {
    const fetchMock = mockFetch({
      'GET /api/agent/checkins': { body: [CHECKIN] },
      'PATCH /api/agent/checkins/3': { body: { ...CHECKIN, enabled: false } },
      'POST /api/agent/checkins/3/run': { body: CHECKIN, status: 202 },
      'DELETE /api/agent/checkins/3': { status: 204 },
    });
    render(
      <>
        <CheckinsPanel configured agentName="Whisk" />
        <ConfirmHost />
      </>,
    );
    expect(await screen.findByText('Morning look')).toBeTruthy();
    expect(screen.getByText(/Mondays at 09:00/)).toBeTruthy();
    expect(screen.getByText(/Nothing to report/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Run now' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/agent/checkins/3/run')).toHaveLength(1));
    fireEvent.click(await screen.findByRole('button', { name: 'Pause' }));
    await waitFor(() => expect(callsTo(fetchMock, 'PATCH', '/api/agent/checkins/3')).toHaveLength(1));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    expect(callsTo(fetchMock, 'DELETE', '/api/agent/checkins/3')).toHaveLength(0);
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/agent/checkins/3')).toHaveLength(1));
  });

  it('disables Run now on a paused one and shows a failing streak', async () => {
    mockFetch({
      'GET /api/agent/checkins': {
        body: [{ ...CHECKIN, enabled: false, last_status: 'error', failures: 10, last_error: 'bad key' }],
      },
    });
    render(<CheckinsPanel configured agentName="Whisk" />);
    expect(await screen.findByText(/Paused/)).toBeTruthy();
    expect(screen.getByText('Failed 10 in a row: bad key')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Run now' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole('button', { name: 'Resume' })).toBeTruthy();
  });

  it('creates a daily check-in', async () => {
    const fetchMock = mockFetch({
      'GET /api/agent/checkins': { body: [] },
      'POST /api/agent/checkins': { body: CHECKIN },
    });
    render(<CheckinsPanel configured={false} agentName="Whisk" />);
    expect(await screen.findByText('No check-ins yet.')).toBeTruthy();
    expect(screen.getByText(/wait until an AI key is added/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Morning look' } });
    fireEvent.change(screen.getByLabelText('What to check'), { target: { value: 'Anything overdue?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add check-in' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/agent/checkins')).toHaveLength(1));
    const [, init] = callsTo(fetchMock, 'POST', '/api/agent/checkins')[0];
    expect(JSON.parse(String(init?.body))).toEqual({
      name: 'Morning look',
      prompt: 'Anything overdue?',
      schedule: 'daily@09:00',
    });
  });
});
