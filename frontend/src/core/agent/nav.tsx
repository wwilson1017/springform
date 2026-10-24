import type { CoreNavItem } from '../shell/coreNav';
import { IconSparkle } from './icons';

export default [
  { to: '/whisk', label: 'Whisk', icon: <IconSparkle size={18} aria-hidden />, placement: 'primary', order: 10 },
] satisfies CoreNavItem[];
