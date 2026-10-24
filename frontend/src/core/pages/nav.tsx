import { IconBook, IconCalendar, IconFile, IconInbox } from '../../shared/icons';
import type { CoreNavItem } from '../shell/coreNav';

export default [
  { to: '/guide', label: 'Guide', icon: <IconBook size={18} aria-hidden />, placement: 'menu', order: 10 },
  { to: '/requests', label: 'Requests', icon: <IconInbox size={18} aria-hidden />, placement: 'menu', order: 20 },
  { to: '/changelog', label: 'Change log', icon: <IconFile size={18} aria-hidden />, placement: 'menu', order: 30 },
  { to: '/jobs', label: 'Jobs', icon: <IconCalendar size={18} aria-hidden />, placement: 'menu', adminOnly: true, order: 80 },
] satisfies CoreNavItem[];
