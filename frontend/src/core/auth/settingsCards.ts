import { lazy } from 'react';
import { toast } from '../../shared/toast';
import type { SettingsSection } from '../settings/settingsSections';
import { GOOGLE_ERRORS } from './api';

const ProfileCard = lazy(() => import('./ProfileCard'));
const SecurityCard = lazy(() => import('./SecurityCard'));
const UsersCard = lazy(() => import('./UsersCard'));
const GoogleConfigCard = lazy(() => import('./GoogleConfigCard'));

/**
 * "Link Google" ends with a full page load of /settings?google=linked or ?google_error=<code>.
 * SettingsPage then redirects to the first section and the query is gone, so the outcome is
 * read here, once, when the page loads.
 */
export function announceGoogleReturn(path: string, search: string) {
  if (path !== '/settings') return;
  const params = new URLSearchParams(search);
  const failed = params.get('google_error');
  if (params.get('google') === 'linked') toast.success('Google account linked. You can now sign in with Google.');
  else if (failed) toast.error(GOOGLE_ERRORS[failed] ?? GOOGLE_ERRORS.google_failed);
}
announceGoogleReturn(window.location.pathname, window.location.search);

// Account is every user's own and comes first; Users and Sign-in are admin-only and come after
// the shell's Workspace (10) and Apps (20).
export default [
  {
    id: 'account', label: 'Account', order: 5, cards: [
      { id: 'profile', title: 'Profile', adminOnly: false, Card: ProfileCard },
      { id: 'security', title: 'Security', adminOnly: false, Card: SecurityCard },
    ],
  },
  { id: 'users', label: 'Users', order: 30, cards: [{ id: 'users', title: 'Users', adminOnly: true, Card: UsersCard }] },
  { id: 'signin', label: 'Sign-in', order: 40, cards: [{ id: 'google', title: 'Google sign-in', adminOnly: true, Card: GoogleConfigCard }] },
] satisfies SettingsSection[];
