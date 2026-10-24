// @vitest-environment jsdom
//
// Renaming a context rewrites every to-do carrying it, and a rename onto an
// existing context MERGES the two — irreversibly from the user's side. What this pins is
// the one thing no type can: the first submit never asks for the merge, the server's 409
// sentence is shown, and only the Merge button sends `merge: true`.
//
// createRoot + React 19 act, following TodoEditSheet.context.test.tsx — no RTL.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

const { renameContextMock } = vi.hoisted(() => ({ renameContextMock: vi.fn() }));
vi.mock('../api', () => ({ renameContext: renameContextMock }));

import { ApiError } from '../errors';
import { ContextRename } from './ContextRename';

let container: HTMLDivElement;
let root: Root;
let onRenamed: Mock<(next: string) => void>;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  renameContextMock.mockReset().mockResolvedValue({});
  onRenamed = vi.fn();
  act(() => { root.render(<ContextRename context="@Baking" onRenamed={onRenamed} />); });
});

afterEach(() => {
  act(() => { root.unmount(); });
  container.remove();
});

const button = (label: string) =>
  [...container.querySelectorAll('button')].find(b => b.textContent === label)!;

function setInput(value: string) {
  const input = container.querySelector('input')!;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function typeAndSave(value: string) {
  act(() => { button('Rename').click(); });
  setInput(value);
  await act(async () => { button('Save').click(); });
}

describe('ContextRename', () => {
  it('renames without asking for a merge', async () => {
    await typeAndSave(' Baking ');
    expect(renameContextMock).toHaveBeenCalledWith('@Baking', 'Baking', false);
    expect(onRenamed).toHaveBeenCalledWith('Baking');
    expect(container.querySelector('input')).toBeNull();
  });

  it('shows the 409 sentence and merges only when Merge is pressed', async () => {
    renameContextMock.mockRejectedValueOnce(
      new ApiError(409, 'You already have a context named "Baking".'),
    );
    await typeAndSave('Baking');
    expect(onRenamed).not.toHaveBeenCalled();
    expect(container.querySelector('[role="alert"]')!.textContent)
      .toBe('You already have a context named "Baking".');
    expect(button('Save')).toBeUndefined();

    await act(async () => { button('Merge').click(); });
    expect(renameContextMock).toHaveBeenLastCalledWith('@Baking', 'Baking', true);
    expect(onRenamed).toHaveBeenCalledWith('Baking');
  });

  it('does not arm Merge for a name typed while the conflict answer was in flight', async () => {
    let reject!: (e: unknown) => void;
    renameContextMock.mockReturnValueOnce(new Promise((_, r) => { reject = r; }));
    await typeAndSave('Baking');
    setInput('Office');
    await act(async () => { reject(new ApiError(409, 'You already have "Baking".')); });
    expect(button('Merge')).toBeUndefined();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('cannot be cancelled once the write is in flight', async () => {
    let resolve!: (v: unknown) => void;
    renameContextMock.mockReturnValueOnce(new Promise(r => { resolve = r; }));
    await typeAndSave('Baking');
    expect(button('Cancel').disabled).toBe(true);
    act(() => {
      container.querySelector('input')!
        .dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });
    expect(container.querySelector('input')).not.toBeNull();
    await act(async () => { resolve({}); });
    expect(onRenamed).toHaveBeenCalledWith('Baking');
  });

  it('sends nothing for a blank or unchanged name', async () => {
    await typeAndSave('   ');
    expect(container.querySelector('[role="alert"]')!.textContent).toMatch(/required/);
    act(() => { button('Cancel').click(); });
    await typeAndSave('@Baking');
    expect(renameContextMock).not.toHaveBeenCalled();
  });
});
