import { describe, expect, it } from 'vitest';
import { describeChange, fieldName, holdsUser, humanize, showValue, type FieldInfo } from './changeText';

const fields: FieldInfo = { favourite_cake: { label: 'Favourite cake', type: 'text' }, rep: { label: 'Account rep', type: 'user' } };
const userName = (id: number) => ({ 2: 'Max Member' }[id] ?? `User #${id}`);

describe('timeline change text', () => {
  it('humanizes column names', () => {
    expect(humanize('value_cents')).toBe('Value');
    expect(humanize('owner_user_id')).toBe('Owner');
    expect(humanize('organization_id')).toBe('Organization');
    expect(humanize('is_private')).toBe('Is private');
  });

  it("names a custom field by its label, falling back to its key when the label isn't known", () => {
    expect(fieldName('field.favourite_cake', fields)).toBe('Favourite cake');
    expect(fieldName('field.new_key', fields)).toBe('New key');
    expect(fieldName('stage', fields)).toBe('Stage');
  });

  it('shows cents as money, user ids as names and lists as text', () => {
    expect(showValue('value_cents', 480000, fields, userName)).toBe('4,800.00');
    expect(showValue('value_cents', 675050, fields, userName)).toBe('6,750.50');
    expect(showValue('value_cents', null, fields, userName)).toBe('empty');
    expect(showValue('owner_user_id', 2, fields, userName)).toBe('Max Member');
    expect(showValue('field.rep', 3, fields, userName)).toBe('User #3');
    expect(showValue('field.tags', ['a', 'b'], fields, userName)).toBe('a, b');
    expect(showValue('size_cents_note', 5, fields, userName)).toBe('5');
    expect(holdsUser('field.favourite_cake', fields)).toBe(false);
  });

  it('reads as a sentence', () => {
    expect(describeChange({ field: 'value_cents', old: 480000, new: 500000 }, {}, userName)).toBe('Value changed from 4,800.00 to 5,000.00');
    expect(describeChange({ field: 'field.favourite_cake', old: null, new: 'Lemon' }, fields, userName))
      .toBe('Favourite cake changed from empty to Lemon');
    expect(describeChange({ field: 'field.rep', old: null, new: 2 }, fields, userName)).toBe('Account rep changed from empty to Max Member');
  });
});
