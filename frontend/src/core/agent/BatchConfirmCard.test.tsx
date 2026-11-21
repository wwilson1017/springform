import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { BatchConfirmCard } from './BatchConfirmCard';
import type { CardPart } from './chatModel';

const member = (id: string, args: Record<string, unknown>, extra: Partial<CardPart> = {}): CardPart => ({
  kind: 'tool',
  tool: 'example_create_widget',
  toolUseId: id,
  args,
  status: 'pending',
  runId: 1,
  batch: 'k',
  confirm: { phase: 'pending' },
  ...extra,
});

describe('BatchConfirmCard', () => {
  it('lists every value of every member, so "1" and 1 read differently', () => {
    render(
      <BatchConfirmCard
        members={[member('a', { name: 'One', n: 1 }), member('b', { name: 'Two', n: '1' })]}
        onDecide={() => {}}
      />,
    );
    for (const text of ['"One"', '"Two"', '1', '"1"']) expect(screen.getByText(text)).toBeTruthy();
    expect(screen.queryByRole('checkbox')).toBeNull(); // no member offered Always allow
  });

  it('Approve all decides each pending member in order, and skips one already decided', async () => {
    const onDecide = vi.fn(async () => {});
    render(
      <BatchConfirmCard
        members={[
          member('a', { name: 'One' }, { canAlwaysAllow: true }),
          member('b', { name: 'Two' }, { canAlwaysAllow: true }),
          member(
            'c',
            { name: 'Three' },
            {
              canAlwaysAllow: true,
              confirm: { phase: 'resolved', decision: 'approve', outcome: 'stale' },
            },
          ),
        ]}
        onDecide={onDecide}
      />,
    );
    expect(screen.getByText('This tool changed since it was proposed; ask again.')).toBeTruthy();
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Approve all 2' }));
    await waitFor(() => expect(onDecide).toHaveBeenCalledTimes(2));
    expect(onDecide.mock.calls).toEqual([
      ['a', 'approve', { alwaysAllow: true }],
      ['b', 'approve', { alwaysAllow: true }],
    ]);
  });

  it('shows a member whose request failed as still waiting, with the failure', () => {
    render(
      <BatchConfirmCard
        members={[
          member('a', { name: 'One' }, { confirm: { phase: 'pending', failure: 'Could not reach the server.' } }),
          member('b', { name: 'Two' }, { confirm: { phase: 'resolved', decision: 'approve', outcome: 'done' } }),
        ]}
        onDecide={() => {}}
      />,
    );
    expect(screen.getByText('Could not reach the server.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Approve all 1' })).toBeTruthy();
  });

  it('Deny all sends the reason with each', async () => {
    const onDecide = vi.fn();
    render(
      <BatchConfirmCard members={[member('a', { name: 'One' }), member('b', { name: 'Two' })]} onDecide={onDecide} />,
    );
    fireEvent.change(screen.getByLabelText('Reason for denying (optional)'), { target: { value: 'No' } });
    fireEvent.click(screen.getByRole('button', { name: 'Deny all' }));
    await waitFor(() => expect(onDecide).toHaveBeenCalledTimes(2));
    expect(onDecide).toHaveBeenLastCalledWith('b', 'deny', { reason: 'No' });
  });
});
