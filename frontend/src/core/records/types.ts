/**
 * Shapes of the record-service routes (custom fields, saved views, reports, notifications,
 * reminders, mentions). Hand-written because those routes return plain dicts, which the OpenAPI
 * schema types as `Record<string, never>`.
 */
import type { UserRef } from '../api/types';

export type FieldType = 'text' | 'number' | 'boolean' | 'date' | 'select' | 'multiselect' | 'url' | 'user';
export const FIELD_TYPES: FieldType[] = ['text', 'number', 'boolean', 'date', 'select', 'multiselect', 'url', 'user'];

/** GET /api/core/fields/definitions */
export interface FieldDefinition {
  id: number;
  entity_type: string;
  key: string;
  label: string;
  type: FieldType;
  options: string[] | null;
  required: boolean;
  position: number;
  archived_at: string | null;
}

/** A stored value: string (text, date, select, url), number, boolean, string[] or a user id. */
export type FieldValue = string | number | boolean | string[] | null;

/** GET /api/core/fields/entity-types */
export interface EntityTypeInfo {
  type: string;
  label: string;
  label_plural: string;
}

/** /api/core/views */
export interface SavedView {
  id: number;
  surface: string;
  entity_type: string | null;
  name: string;
  /** Server-owned edit counter; a PATCH must send the current one. */
  version: number;
  payload: Record<string, unknown>;
  owner: UserRef;
  is_shared: boolean;
  can_edit: boolean;
  created_at: string;
  updated_at: string;
}

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

/** GET /api/core/reports */
export interface ReportInfo {
  key: string;
  label: string;
  app: string;
  params: ReportParamsSchema | null;
  admin_only: boolean;
}

/** GET /api/core/reports/{key} */
export interface ReportResult {
  columns: string[];
  rows: unknown[][];
}

/** /api/core/notifications */
export interface AppNotification {
  id: number;
  title: string;
  message: string;
  entity_type: string | null;
  entity_id: number | null;
  link: string | null;
  created_at: string;
  read_at: string | null;
}

export type ReminderFreq = 'daily' | 'weekly' | 'monthly' | 'yearly';
export type ReminderStatus = 'open' | 'done' | 'voided' | 'snoozed';

/** /api/core/reminders */
export interface Reminder {
  id: number;
  owner: UserRef;
  mine: boolean;
  entity_type: string | null;
  entity_id: number | null;
  entity_title: string | null;
  link: string | null;
  title: string;
  note: string;
  due_at: string;
  repeat: { freq: ReminderFreq; anchor: string; time: string; tz: string } | null;
  series_id: number;
  status: ReminderStatus;
  void_reason: string | null;
  fired_at: string | null;
  created_at: string;
  updated_at: string;
}
