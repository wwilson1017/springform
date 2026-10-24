import { describe, expect, it } from 'vitest';
import { parseOwnerParam, touchDetailPath } from './touches';

describe('weekly touches routing', () => {
  it('links to a rep, carrying an applied range as days', () => {
    expect(touchDetailPath(4, null)).toBe('/crm/touches/4');
    expect(touchDetailPath(null, { start: '2026-10-01', end: '2026-10-07' })).toBe('/crm/touches/unassigned?start=2026-10-01&end=2026-10-07');
  });

  it('accepts only an owner the API accepts', () => {
    expect(parseOwnerParam('unassigned')).toBe('unassigned');
    expect(parseOwnerParam('12')).toBe('12');
    for (const bad of [undefined, '0', '-1', '1e3', '99999999999', 'me']) expect(parseOwnerParam(bad), String(bad)).toBeNull();
  });
});
