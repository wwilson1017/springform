/**
 * Shapes and wording for the sign-in, invite, 2FA and user-admin routes in backend/core/auth/.
 * The backend declares no response models for these, so they are typed here.
 */

import { ApiError } from '../api/client';
import type { Role, User } from '../api/types';

/** What every first factor (password, invite, reset) answers: a session, or the TOTP step. */
export type LoginResult = { user: User } | { totp_required: true; challenge: string };

export const needsChallenge = (r: LoginResult): r is { totp_required: true; challenge: string } =>
  'totp_required' in r && r.totp_required;

/** GET /api/auth/users */
export interface AdminUser {
  id: number;
  email: string;
  name: string;
  role: Role;
  tz: string | null;
  is_active: boolean;
  invite_pending: boolean;
  has_password: boolean;
  google_linked: boolean;
  totp_enabled: boolean;
  invited_by: number | null;
  last_login_at: string | null;
  deactivated_at: string | null;
  created_at: string;
}

export interface InviteLink {
  invite_url: string;
  /** False when mail is not configured or Resend refused it: the admin sends the link. */
  mailed: boolean;
}

export interface TotpStatus {
  enabled: boolean;
  backup_codes_left: number;
}

export interface TrustedDevice {
  label: string;
  created_at: string;
  expires_at: string;
  current: boolean;
}

export interface GoogleStatus {
  available: boolean;
  linked: boolean;
  has_password: boolean;
}

export interface GoogleConfig {
  client_id: string;
  has_secret: boolean;
  redirect_uri: string;
  require_totp_for_google: boolean;
}

export interface GoogleTest {
  redirect_uri: string;
  client_id_valid: boolean;
  has_secret: boolean;
  ok: boolean;
  problems: string[];
}

/** Every `?error=` / `?google_error=` the Google callback and start routes redirect with. */
export const GOOGLE_ERRORS: Record<string, string> = {
  google_failed: "Google sign-in didn't finish. Try again.",
  not_invited: "That Google account hasn't been invited. Ask an admin for an invite.",
  link_required: 'That Google account isn\'t linked to your account yet. Sign in with your password, then link Google under Settings → Account.',
  google_mismatch: 'Your account is linked to a different Google account. Use that one, or sign in with your password.',
  google_not_configured: "Google sign-in isn't set up on this install yet.",
  invite_invalid: 'This invite link has expired or was already used. Ask an admin to send a new one.',
  google_in_use: 'That Google account is already linked to another user. Pick a different one.',
};

/**
 * The message for a failed call: a known code from `codes`, else the server's own sentence (the
 * backend answers some 409/422s with a full sentence), else `fallback`.
 */
export function errorText(err: unknown, codes: Record<string, string>, fallback: string): string {
  if (!(err instanceof ApiError)) return "Can't reach the server. Try again in a moment.";
  if (codes[err.detail]) return codes[err.detail];
  if (err.status === 429) return 'Too many attempts. Wait a few minutes, then try again.';
  // A sentence, not a code like `invalid` or a status text like `Unprocessable Entity`.
  if (err.status < 500 && /\s/.test(err.detail) && /[.!?]$/.test(err.detail)) return err.detail;
  return fallback;
}

export const inputSm =
  'box-border w-full rounded-md border border-sf-line-strong bg-sf-card px-3 py-2 text-sm text-sf-ink placeholder:text-sf-ink-dim disabled:opacity-60';
export const labelSm = 'mb-1 block text-xs font-medium text-sf-ink-soft';
export const btnPrimary =
  'cursor-pointer rounded-md border-0 bg-sf-accent px-4 py-2 text-sm font-medium text-sf-accent-ink disabled:cursor-default disabled:opacity-50';
export const btnSecondary =
  'cursor-pointer rounded-md border border-sf-line-strong bg-transparent px-3 py-2 text-sm text-sf-ink hover:bg-sf-hover disabled:cursor-default disabled:opacity-50';
export const btnDanger =
  'cursor-pointer rounded-md border border-sf-red bg-transparent px-3 py-2 text-sm text-sf-red-text hover:bg-sf-hover disabled:cursor-default disabled:opacity-50';
export const btnLink = 'cursor-pointer border-0 bg-transparent p-0 text-sm text-sf-accent-text hover:underline disabled:opacity-50';
export const alertText = 'm-0 text-sm text-sf-red-text';
export const noteText = 'm-0 text-sm text-sf-ink-mute';
