/**
 * Hand-written shapes for the core API the shell calls. They mirror the backend contract until
 * `types.gen.ts` is generated from the OpenAPI schema; then these become aliases of
 * `components['schemas'][...]` or go away.
 */

export type Role = 'admin' | 'member';

export interface AuthStatus {
  setup_required: boolean;
  google: boolean;
  preview: boolean;
}

/** GET /api/me */
export interface User {
  id: number;
  email: string;
  name: string;
  role: Role;
  tz: string;
}

export interface UserRef {
  id: number;
  name: string;
}

export interface SettingsCardManifest {
  id: string;
  title: string;
  admin_only: boolean;
}

/** One item of GET /api/core/apps: the caller's apps; admins also get hidden ones. */
export interface CoreApp {
  slug: string;
  name: string;
  description: string;
  path: string;
  icon: string;
  roles: Role[];
  order: number;
  /** The app's badge route (returns `Badge`), or null. */
  badge: string | null;
  hidden: boolean;
  settings_cards: SettingsCardManifest[];
  version: string;
}

export interface Badge {
  count: number;
  label?: string;
}

export interface FieldChange {
  field: string;
  old: unknown;
  new: unknown;
}

export interface TimelineEntry {
  id: number;
  kind: 'note' | 'comment' | 'field_change' | 'system';
  body: string | null;
  /** One item per changed field on a `field_change` entry. */
  changes: FieldChange[] | null;
  author: UserRef | null;
  created_at: string;
}

export interface FileRecord {
  id: number;
  filename: string;
  mime_type: string;
  byte_size: number;
  sha256: string;
  created_at: string;
  uploaded_by: UserRef | null;
  /** A JPEG thumbnail is served at /api/core/files/{id}/thumb. */
  has_thumb: boolean;
}
