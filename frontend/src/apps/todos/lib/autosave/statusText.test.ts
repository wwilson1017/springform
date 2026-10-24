// The words the ambient indicator says (#2032). Copy is the whole feature here — "All
// changes saved" IS the reassurance Will asked for — so it is pinned rather than left to
// drift, and the failure states must name themselves rather than reading as saved.
import { describe, expect, it } from 'vitest';

import { STATUS_TONE, saveStatusText } from './statusText';

describe('saveStatusText', () => {
  it('reassures when there is nothing outstanding', () => {
    expect(saveStatusText('idle')).toBe('All changes saved');
    expect(saveStatusText('saved')).toBe('All changes saved');
  });

  it('names the in-between states', () => {
    expect(saveStatusText('dirty')).toBe('Unsaved changes');
    expect(saveStatusText('saving')).toBe('Saving…');
  });

  it('never lets a failure read as saved', () => {
    // Must not name a culprit: a lost-response retry produces the same 409 against your
    // own save, and this is the announced string.
    expect(saveStatusText('conflict')).toBe('Not saved — this record changed');
    expect(saveStatusText('conflict')).not.toContain('someone else');
    expect(saveStatusText('error', 'API error 500: boom')).toBe('Not saved — API error 500: boom');
    expect(saveStatusText('error')).toBe('Not saved');
  });
});

describe('STATUS_TONE', () => {
  it('tints every failure with a themed status token', () => {
    // A fixed hue keeps its light value in dark mode and turns unreadable; the `-text` status
    // tokens are redefined under .dark (index.css), so a failure must use one.
    expect(STATUS_TONE.conflict).toMatch(/\btext-sf-(amber|red)-text\b/);
    expect(STATUS_TONE.error).toMatch(/\btext-sf-(amber|red)-text\b/);
  });
});
