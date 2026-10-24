import { describe, expect, it } from 'vitest';
import { describeChange, fieldName, humanize, showValue } from './changeText';

describe('timeline change text', () => {
  it('humanizes column names', () => {
    expect(humanize('value_cents')).toBe('Value');
    expect(humanize('owner_user_id')).toBe('Owner');
    expect(humanize('organization_id')).toBe('Organization');
    expect(humanize('is_private')).toBe('Is private');
  });

  it("names a custom field by its label, falling back to its key when the label isn't known", () => {
    const labels = { favourite_cake: 'Favourite cake' };
    expect(fieldName('field.favourite_cake', labels)).toBe('Favourite cake');
    expect(fieldName('field.new_key', labels)).toBe('New key');
    expect(fieldName('stage', labels)).toBe('Stage');
  });

  it('shows cents as money and lists as text', () => {
    expect(showValue('value_cents', 480000)).toBe('4,800.00');
    expect(showValue('value_cents', 675050)).toBe('6,750.50');
    expect(showValue('value_cents', null)).toBe('empty');
    expect(showValue('field.tags', ['a', 'b'])).toBe('a, b');
    expect(showValue('size_cents_note', 5)).toBe('5');
  });

  it('reads as a sentence', () => {
    expect(describeChange({ field: 'value_cents', old: 480000, new: 500000 }, {})).toBe('Value changed from 4,800.00 to 5,000.00');
    expect(describeChange({ field: 'field.favourite_cake', old: null, new: 'Lemon' }, { favourite_cake: 'Favourite cake' }))
      .toBe('Favourite cake changed from empty to Lemon');
  });
});
