import { describe, expect, it } from 'vitest';
import type { TouchWindow } from './api';
import { parseOwnerParam, touchDetailPath, windowText } from './touches';

// A custom window as the API answers it in America/Chicago: the instants are UTC, so the end
// instant falls on the day after the last day the window covers.
const custom: TouchWindow = {
  custom: true, label: '2026-10-01 – 2026-10-07',
  start: '2026-10-01T05:00:00Z', end: '2026-10-08T05:00:00Z', start_day: '2026-10-01', end_day: '2026-10-07',
};
const rolling: TouchWindow = {
  custom: false, label: 'Last 7 days',
  start: '2026-10-17T22:30:00Z', end: '2026-10-25T03:10:00Z', start_day: '2026-10-17', end_day: '2026-10-24',
};

describe('weekly touches routing', () => {
  it('links to a rep, carrying a custom window as the days the API applied', () => {
    expect(touchDetailPath(4, rolling)).toBe('/crm/touches/4');
    expect(touchDetailPath(null, custom)).toBe('/crm/touches/unassigned?start=2026-10-01&end=2026-10-07');
  });

  it('shows the window by its install-local days, not its UTC instants', () => {
    expect(windowText(custom)).toBe('Oct 1 – Oct 7, 2026');
    expect(windowText(rolling)).toBe('Last 7 days · Oct 17 – Oct 24, 2026');
    expect(windowText({ ...custom, start_day: '2025-12-29', end_day: '2026-01-04' })).toBe('Dec 29, 2025 – Jan 4, 2026');
    expect(windowText({ ...custom, start_day: '2026-10-07' })).toBe('Oct 7, 2026');
  });

  it('accepts only an owner the API accepts', () => {
    expect(parseOwnerParam('unassigned')).toBe('unassigned');
    expect(parseOwnerParam('12')).toBe('12');
    for (const bad of [undefined, '0', '-1', '1e3', '99999999999', 'me']) expect(parseOwnerParam(bad), String(bad)).toBeNull();
  });
});
