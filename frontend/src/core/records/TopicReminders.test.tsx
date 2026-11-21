import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ConfirmHost } from '../../shared/ConfirmHost';
import { callsTo, mockFetch, type Reply } from '../../testing';
import { INTENTS, TopicReminders } from './TopicReminders';
import type { TopicReminder } from './types';

const oven: TopicReminder = {
  id: 4,
  terms: ['walk-in freezer', 'freezer service'],
  note: 'Book the service visit',
  fires: 1,
  max_fires: 3,
  cooldown_hours: 24,
  last_fired_at: '2026-11-21T09:00:00Z',
  expires_at: '2027-02-19T09:00:00Z',
  created_at: '2026-11-21T08:00:00Z',
  status: 'active',
};

afterEach(() => vi.unstubAllGlobals());

describe('TopicReminders', () => {
  it('lists the reminders and deletes one only after the confirm', async () => {
    const routes: Record<string, Reply> = {
      [`GET ${INTENTS}`]: { body: [oven] },
      [`DELETE ${INTENTS}/4`]: { body: { deleted: true } },
    };
    const fetchMock = mockFetch(routes);
    render(
      <>
        <TopicReminders />
        <ConfirmHost />
      </>,
    );
    expect(await screen.findByText('walk-in freezer, freezer service')).toBeTruthy();
    expect(screen.getByText('Book the service visit')).toBeTruthy();
    expect(screen.getByText('Shown 1 of 3 times')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Delete topic reminder walk-in freezer, freezer service' }));
    expect(callsTo(fetchMock, 'DELETE', `${INTENTS}/4`)).toHaveLength(0);
    routes[`GET ${INTENTS}`] = { body: [] };
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    expect(await screen.findByText('No topic reminders yet.')).toBeTruthy();
    expect(callsTo(fetchMock, 'DELETE', `${INTENTS}/4`)).toHaveLength(1);
  });
});
