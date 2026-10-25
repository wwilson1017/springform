/**
 * Shapes of the record-service routes (custom fields, saved views, reports, notifications,
 * reminders). Responses are the generated schemas; a report's params schema is typed here because
 * the server passes it through as a free-form dict.
 */
import type { components } from '../api/types.gen';

type S = components['schemas'];

/** GET /api/core/fields/definitions */
export type FieldDefinition = S['FieldDefinition'];
export type FieldType = FieldDefinition['type'];
export const FIELD_TYPES: FieldType[] = ['text', 'number', 'boolean', 'date', 'select', 'multiselect', 'url', 'user'];

/** A stored value: string (text, date, select, url), number, boolean, string[] or a user id. */
export type FieldValue = string | number | boolean | string[] | null;

/** GET /api/core/fields/entity-types */
export type EntityTypeInfo = S['FieldEntityType'];

/** /api/core/views. `version` is the server-owned edit counter; a PATCH must send the current one. */
export type SavedView = S['SavedView'];

export type ReportParamType = 'string' | 'integer' | 'number' | 'boolean';

export interface ReportParam {
  type: ReportParamType;
  format?: 'date';
  enum?: Array<string | number | boolean>;
  default?: string | number | boolean;
  title?: string;
  description?: string;
}

export interface ReportParamsSchema {
  type: 'object';
  properties?: Record<string, ReportParam>;
  required?: string[];
}

/** GET /api/core/reports. `params` is a JSON schema; read it as `ReportParamsSchema`. */
export type ReportInfo = S['ReportInfo'];

/** GET /api/core/reports/{key} */
export type ReportResult = S['ReportResult'];

/** /api/core/notifications */
export type AppNotification = S['Notification'];

/** /api/core/reminders */
export type Reminder = S['Reminder'];
export type ReminderFreq = NonNullable<Reminder['repeat']>['freq'];
export type ReminderStatus = Reminder['status'];

/** GET /api/core/notifications/unread-count */
export type UnreadCount = S['UnreadCount'];
/** GET /api/core/notifications/push/public-key */
export type PushPublicKey = S['PushPublicKey'];
