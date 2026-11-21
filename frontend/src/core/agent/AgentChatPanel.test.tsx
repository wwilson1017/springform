import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AgentChatPanel } from './AgentChatPanel';

describe('AgentChatPanel while a reply runs', () => {
  it('keeps the composer usable: a typed message sends (to be queued) beside Stop', () => {
    const onSend = vi.fn();
    render(
      <AgentChatPanel
        agentName="Whisk"
        messages={[
          { id: 'u1', role: 'user', parts: [{ kind: 'text', text: 'hi' }] },
          { id: 'u2', role: 'user', parts: [{ kind: 'text', text: 'also this' }], queued: true },
        ]}
        streaming
        usage={null}
        notice={null}
        onSend={onSend}
        onStop={() => {}}
        onDecide={() => {}}
      />,
    );
    expect(screen.getByText('Queued until the current step finishes')).toBeTruthy();
    const input = screen.getByLabelText('Message Whisk');
    expect(input.hasAttribute('disabled')).toBe(false);
    expect(screen.queryByRole('button', { name: 'Send' })).toBeNull(); // nothing typed: only Stop
    fireEvent.change(input, { target: { value: 'and that' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSend).toHaveBeenCalledWith('and that');
    expect(screen.getByRole('button', { name: 'Stop' })).toBeTruthy();
  });
});
