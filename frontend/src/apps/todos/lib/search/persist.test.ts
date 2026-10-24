import { describe, expect, it } from 'vitest';
import { toggleValue } from './persist';

describe('toggleValue', () => {
  it('adds a missing value and removes a present one, without mutating', () => {
    const list = ['a', 'b'];
    expect(toggleValue(list, 'c')).toEqual(['a', 'b', 'c']);
    expect(toggleValue(list, 'a')).toEqual(['b']);
    expect(list).toEqual(['a', 'b']);
  });
});
