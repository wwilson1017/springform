import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Dialog } from './Dialog';

describe('Dialog', () => {
  it('closes on Escape, but not while focus is in a dialog opened over it', () => {
    const onClose = vi.fn();
    render(
      <>
        <Dialog title="Edit" onClose={onClose}><input aria-label="Field" /></Dialog>
        <div role="dialog" aria-label="Confirm"><button type="button">Delete</button></div>
      </>,
    );
    screen.getByRole('button', { name: 'Delete' }).focus();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
    screen.getByLabelText('Field').focus();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('leaves Escape to an open picker inside it', () => {
    const onClose = vi.fn();
    render(<Dialog title="New" onClose={onClose}><input role="combobox" aria-expanded="true" aria-controls="x" aria-label="Person" /></Dialog>);
    screen.getByLabelText('Person').focus();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
  });
});
