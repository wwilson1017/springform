import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ToolPart } from './chatModel';
import type { ConfirmState } from './confirmState';
import { ToolConfirmCard } from './ToolConfirmCard';

const part = (extra: Partial<ToolPart> = {}): ToolPart & { confirm: ConfirmState } => ({
  kind: 'tool',
  tool: 'example_create_widget',
  toolUseId: 'u1',
  args: { name: 'Gizmo' },
  status: 'pending',
  runId: 9,
  confirm: { phase: 'pending' },
  ...extra,
});

describe('ToolConfirmCard', () => {
  it('offers Always allow only when the server said it may', () => {
    const { rerender } = render(<ToolConfirmCard part={part()} onDecide={() => {}} />);
    expect(screen.queryByRole('checkbox')).toBeNull();
    rerender(<ToolConfirmCard part={part({ canAlwaysAllow: true })} onDecide={() => {}} />);
    expect(screen.getByRole('checkbox')).toBeTruthy();
  });

  it('sends the ticked box with Approve and the typed reason with Deny', () => {
    const onDecide = vi.fn();
    render(<ToolConfirmCard part={part({ canAlwaysAllow: true })} onDecide={onDecide} />);
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect(onDecide).toHaveBeenLastCalledWith('approve', { alwaysAllow: true });
    fireEvent.change(screen.getByLabelText('Reason for denying (optional)'), { target: { value: 'Wrong one' } });
    fireEvent.click(screen.getByRole('button', { name: 'Deny' }));
    expect(onDecide).toHaveBeenLastCalledWith('deny', { reason: 'Wrong one' });
  });
});
