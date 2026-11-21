import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AgentChatPanel } from './AgentChatPanel';

function panel() {
  const onSend = vi.fn();
  render(
    <AgentChatPanel
      agentName="Helper"
      messages={[]}
      streaming={false}
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

  it('refuses a type the server does not read and a sixth file', () => {
    const { attach } = panel();
    attach(new File(['x'], 'run.exe'));
    expect(screen.queryByText('run.exe')).toBeNull();
    attach(...Array.from({ length: 6 }, (_, i) => new File(['a'], `t${i}.csv`)));
    expect(screen.getAllByRole('listitem')).toHaveLength(5);
  });
});
