import { IconInbox } from '../../shared/icons';
import type { CoreNavItem } from '../shell/coreNav';

export default [
  { to: '/backups', label: 'Backups', icon: <IconInbox size={18} aria-hidden />, placement: 'menu', adminOnly: true },
] satisfies CoreNavItem[];
