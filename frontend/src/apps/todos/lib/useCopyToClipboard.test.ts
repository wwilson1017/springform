// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { copyToClipboard } from './useCopyToClipboard';

function setClipboard(value: unknown) {
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value });
}

/** jsdom has no execCommand; install one that records what was selected. */
function stubExecCommand(result: boolean | Error) {
  const seen: string[] = [];
  (document as unknown as { execCommand: (c: string) => boolean }).execCommand = (cmd: string) => {
    const el = document.activeElement as HTMLTextAreaElement;
    seen.push(`${cmd}:${el.value.slice(el.selectionStart ?? 0, el.selectionEnd ?? 0)}`);
    if (result instanceof Error) throw result;
    return result;
  };
  return seen;
}

afterEach(() => {
  setClipboard(undefined);
  delete (document as unknown as { execCommand?: unknown }).execCommand;
  document.body.innerHTML = '';
});

describe('copyToClipboard', () => {
  it('uses the clipboard API when there is one', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });
    const seen = stubExecCommand(true);
    expect(await copyToClipboard('hello')).toBe(true);
    expect(writeText).toHaveBeenCalledWith('hello');
    expect(seen).toEqual([]);
  });

  it('falls back to execCommand in a non-secure context (no navigator.clipboard)', async () => {
    setClipboard(undefined);
    const seen = stubExecCommand(true);
    const field = document.createElement('input');
    document.body.appendChild(field);
    field.focus();

    expect(await copyToClipboard('http://192.168.1.199:8600/w/abc')).toBe(true);
    expect(seen).toEqual(['copy:http://192.168.1.199:8600/w/abc']);
    // The scratch textarea is gone and focus is back where it was.
    expect(document.querySelector('textarea')).toBeNull();
    expect(document.activeElement).toBe(field);
  });

  it('falls back when the clipboard API rejects', async () => {
    setClipboard({ writeText: () => Promise.reject(new Error('denied')) });
    const seen = stubExecCommand(true);
    expect(await copyToClipboard('x')).toBe(true);
    expect(seen).toEqual(['copy:x']);
  });

  it('reports failure when both routes fail', async () => {
    setClipboard(undefined);
    stubExecCommand(false);
    expect(await copyToClipboard('x')).toBe(false);
    stubExecCommand(new Error('not allowed'));
    expect(await copyToClipboard('x')).toBe(false);
    expect(document.querySelector('textarea')).toBeNull();
  });
});
