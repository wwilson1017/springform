/**
 * How a timeline field change reads. The server reports columns by name (`value_cents`,
 * `is_private`) and custom fields as `field.<key>`; people read labels and money.
 */
import type { FieldChange } from '../api/types';

/** "value_cents" → "Value", "owner_user_id" → "Owner", "is_private" → "Is private". */
export function humanize(column: string): string {
  const words = column.replace(/(_user_id|_cents|_id)$/, '').replace(/_/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The name a change is shown under: a custom field's label (`labels` by key), else the column, humanized. */
export function fieldName(field: string, labels: Record<string, string>): string {
  if (field.startsWith('field.')) {
    const key = field.slice('field.'.length);
    return labels[key] ?? humanize(key);
  }
  return humanize(field);
}

// simplification: amounts show without a currency symbol, since a change row doesn't carry the
// record's currency; upgrade path: the change carries it, or the app renders its own rows.
const money = new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function showValue(field: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return 'empty';
  if (field.endsWith('_cents') && typeof value === 'number') return money.format(value / 100);
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'empty';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

/** "Value changed from 4,800.00 to 5,000.00" */
export function describeChange(c: FieldChange, labels: Record<string, string>): string {
  return `${fieldName(c.field, labels)} changed from ${showValue(c.field, c.old)} to ${showValue(c.field, c.new)}`;
}
