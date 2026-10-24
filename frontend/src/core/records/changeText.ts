/**
 * How a timeline field change reads. The server reports columns by name (`value_cents`,
 * `owner_user_id`) and custom fields as `field.<key>`; people read labels, money and names.
 */
import type { FieldChange } from '../api/types';
import type { FieldDefinition } from './types';

/** The record type's custom fields by key: what a `field.<key>` change is called and holds. */
export type FieldInfo = Record<string, Pick<FieldDefinition, 'label' | 'type'>>;

/** "value_cents" → "Value", "owner_user_id" → "Owner", "is_private" → "Is private". */
export function humanize(column: string): string {
  const words = column.replace(/(_user_id|_cents|_id)$/, '').replace(/_/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const customKey = (field: string) => (field.startsWith('field.') ? field.slice('field.'.length) : null);

/** The name a change is shown under: a custom field's label, else the column (or key), humanized. */
export function fieldName(field: string, fields: FieldInfo): string {
  const key = customKey(field);
  return key === null ? humanize(field) : fields[key]?.label ?? humanize(key);
}

/** Whether the field holds a user id: an `*_user_id` column or a custom field of type user. */
export function holdsUser(field: string, fields: FieldInfo): boolean {
  const key = customKey(field);
  return key === null ? field.endsWith('_user_id') : fields[key]?.type === 'user';
}

// simplification: amounts show without a currency symbol, since a change row doesn't carry the
// record's currency; upgrade path: the change carries it, or the app renders its own rows.
const money = new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function showValue(field: string, value: unknown, fields: FieldInfo, userName: (id: number) => string): string {
  if (value === null || value === undefined || value === '') return 'empty';
  if (typeof value === 'number' && field.endsWith('_cents')) return money.format(value / 100);
  if (typeof value === 'number' && holdsUser(field, fields)) return userName(value);
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'empty';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

/** "Value changed from 4,800.00 to 5,000.00" */
export function describeChange(c: FieldChange, fields: FieldInfo, userName: (id: number) => string): string {
  const show = (v: unknown) => showValue(c.field, v, fields, userName);
  return `${fieldName(c.field, fields)} changed from ${show(c.old)} to ${show(c.new)}`;
}
