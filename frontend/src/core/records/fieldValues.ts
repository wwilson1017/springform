/**
 * Custom-field values between the wire and the inputs. A draft is what an input holds: a string
 * for every type except multiselect (a list), so a half-typed number survives a re-render.
 * `fromDraft` turns it back into the typed value the server stores; null clears the field.
 */
import type { FieldDefinition, FieldValue } from './types';

export type Draft = string | string[];

export function toDraft(def: FieldDefinition, value: FieldValue | undefined): Draft {
  if (def.type === 'multiselect') return Array.isArray(value) ? value : [];
  if (value === null || value === undefined) return '';
  if (def.type === 'boolean') return value ? 'yes' : 'no';
  return String(value);
}

/** The typed value for `draft`, or an Error naming what was expected. */
export function fromDraft(def: FieldDefinition, draft: Draft): FieldValue | Error {
  if (Array.isArray(draft)) return draft.length ? draft : null;
  const text = draft.trim();
  if (text === '') return null;
  switch (def.type) {
    case 'number': {
      const n = Number(text);
      return Number.isFinite(n) ? n : new Error(`${def.label}: expected a number`);
    }
    case 'boolean':
      return text === 'yes';
    case 'user':
      return Number(text);
    default:
      return text;
  }
}

/** True when the draft would store something different from `value`. */
export function draftChanged(def: FieldDefinition, value: FieldValue | undefined, draft: Draft): boolean {
  const next = fromDraft(def, draft);
  if (next instanceof Error) return true;
  return JSON.stringify(next) !== JSON.stringify(value ?? null);
}

/** How a stored value reads on the record page. `userName` resolves a `user` field's id. */
export function displayValue(def: FieldDefinition, value: FieldValue | undefined, userName: (id: number) => string): string {
  if (value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0)) return '—';
  if (def.type === 'boolean') return value ? 'Yes' : 'No';
  if (def.type === 'user') return userName(Number(value));
  if (Array.isArray(value)) return value.join(', ');
  return String(value);
}
