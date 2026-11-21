import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { toast } from '../../shared/toast';
import { AgentChatPanel } from './AgentChatPanel';
import { ATTACH_WHILE_RUNNING } from './useAgentChat';

function panel(streaming = false) {
  const onSend = vi.fn();
  render(
    <AgentChatPanel
      agentName="Helper"
      messages={[]}
      streaming={streaming}
      usage={null}
      notice={null}
      onSend={onSend}
      onStop={() => {}}
      onDecide={() => {}}
    />,
  );
  const attach = (...files: File[]) => fireEvent.change(screen.getByTestId('chat-file-input'), { target: { files } });
  return { onSend, attach };
}

describe('AgentChatPanel attachments', () => {
  it('shows a chip per file, removes one, and sends files without text', () => {
    const { onSend, attach } = panel();
    const send = screen.getByRole<HTMLButtonElement>('button', { name: 'Send' });
    expect(send.disabled).toBe(true);
    attach(new File(['x'], 'shelf.png', { type: 'image/png' }), new File(['a,b'], 'parts.csv'));
    expect(screen.getByText('shelf.png')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Remove shelf.png' }));
    expect(screen.queryByText('shelf.png')).toBeNull();
    expect(send.disabled).toBe(false);
    fireEvent.click(send);
    expect(onSend).toHaveBeenCalledWith('', [expect.objectContaining({ name: 'parts.csv' })]);
    expect(screen.queryByText('parts.csv')).toBeNull();
  });

  it('says attachments wait for the reply to finish, and keeps the draft and files', () => {
    const error = vi.spyOn(toast, 'error');
    const { onSend, attach } = panel(true);
    attach(new File(['a,b'], 'parts.csv'));
    const input = screen.getByLabelText('Message Helper');
    fireEvent.change(input, { target: { value: 'and this' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(error).toHaveBeenCalledWith(ATTACH_WHILE_RUNNING);
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByText('parts.csv')).toBeTruthy();
    expect((input as HTMLTextAreaElement).value).toBe('and this');
    error.mockRestore();
  });

  it('refuses a type the server does not read and a sixth file', () => {
    const { attach } = panel();
    attach(new File(['x'], 'run.exe'));
    expect(screen.queryByText('run.exe')).toBeNull();
    attach(...Array.from({ length: 6 }, (_, i) => new File(['a'], `t${i}.csv`)));
    expect(screen.getAllByRole('listitem')).toHaveLength(5);
  });
});

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
    expect(onSend).toHaveBeenCalledWith('and that', []);
    expect(screen.getByRole('button', { name: 'Stop' })).toBeTruthy();
  });
});
