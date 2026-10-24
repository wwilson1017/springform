import { lazy } from 'react';
import type { SettingsSection } from '../settings/settingsSections';

// Both cards are lazy: they load only when their Settings section opens.
export default [
  {
    id: 'notifications', label: 'Notifications', order: 8,
    cards: [{ id: 'push', title: 'Push notifications', adminOnly: false, Card: lazy(() => import('./PushCard')) }],
  },
  {
    id: 'records', label: 'Records', order: 35,
    cards: [{ id: 'custom-fields', title: 'Custom fields', adminOnly: true, Card: lazy(() => import('./CustomFieldSettings')) }],
  },
] satisfies SettingsSection[];
