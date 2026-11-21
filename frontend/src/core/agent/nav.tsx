import type { CoreNavItem } from '../shell/coreNav';
import { IconSparkle } from './icons';
import { AgentName } from './useAgentName';

export default [
  { to: '/whisk', label: <AgentName />, icon: <IconSparkle size={18} aria-hidden />, placement: 'primary', order: 10 },
] satisfies CoreNavItem[];
