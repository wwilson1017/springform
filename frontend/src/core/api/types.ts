/**
 * Core API shapes the shell calls. Response shapes are the generated schemas (`types.gen.ts`);
 * only routes without a response model keep a hand-written shape here.
 */
import type { components } from './types.gen';

type S = components['schemas'];

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

export type UserRef = S['UserRef'];
export type SettingsCard = S['SettingsCard'];
/** One item of GET /api/core/apps: the caller's apps; admins also get hidden ones. */
export type CoreApp = S['CoreApp'];
export type Badge = S['Badge'];
export type FieldChange = S['FieldChange'];
export type TimelineEntry = S['TimelineEntry'];
/** A JPEG thumbnail is served at /api/core/files/{id}/thumb when `has_thumb`. */
export type FileRecord = S['File'];
