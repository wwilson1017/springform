import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ChunkErrorBoundary from './ChunkErrorBoundary';

function ChunkGone(): never {
  throw new Error('Failed to fetch dynamically imported module: /assets/Page-abc123.js');
}
function RenderBug(): never {
  throw new Error("Cannot read properties of undefined (reading 'map')");
}

let reload: ReturnType<typeof vi.fn>;

beforeEach(() => {
  sessionStorage.clear();
  reload = vi.fn();
  vi.stubGlobal('location', { reload });
  vi.spyOn(console, 'error').mockImplementation(() => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('ChunkErrorBoundary', () => {
  it('reloads once per tab session on a chunk-load failure, then leaves the card up', () => {
    const first = render(<ChunkErrorBoundary><ChunkGone /></ChunkErrorBoundary>);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('alert').textContent).toContain('Couldn’t load this page.');
    first.unmount();
    render(<ChunkErrorBoundary><ChunkGone /></ChunkErrorBoundary>);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('never reloads on a render bug, nor for a panel', () => {
    render(<ChunkErrorBoundary scope="route"><RenderBug /></ChunkErrorBoundary>);
    render(<ChunkErrorBoundary scope="panel"><ChunkGone /></ChunkErrorBoundary>);
    expect(reload).not.toHaveBeenCalled();
    expect(screen.getAllByRole('alert').map(a => a.textContent)).toEqual([
      expect.stringContaining('Something went wrong on this page.'),
      expect.stringContaining('Couldn’t load this panel.'),
    ]);
  });
});
