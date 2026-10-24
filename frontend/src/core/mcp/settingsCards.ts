import { lazy } from 'react';
import type { SettingsSection } from '../settings/settingsSections';

// Member-visible: every user can make links that act as themselves.
export default [
  {
    id: 'mcp', label: 'MCP', order: 20,
    cards: [{ id: 'connector', title: 'MCP connector', adminOnly: false, Card: lazy(() => import('./McpLinksCard')) }],
  },
] satisfies SettingsSection[];
