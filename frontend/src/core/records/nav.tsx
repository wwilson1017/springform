import { IconCalendar, IconChart } from '../../shared/icons';
import type { CoreNavItem } from '../shell/coreNav';

export default [
  { to: '/reminders', label: 'Reminders', icon: <IconCalendar size={18} aria-hidden />, placement: 'menu', order: 30 },
  { to: '/reports', label: 'Reports', icon: <IconChart size={18} aria-hidden />, placement: 'menu', order: 40 },
] satisfies CoreNavItem[];
