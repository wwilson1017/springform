import { lazy } from 'react';
import type { SettingsSection } from '../settings/settingsSections';

// Eager module, lazy card: the card loads when Settings, MCP servers is opened.
export default [
  {
    id: 'mcp_servers', label: 'MCP servers', order: 80,
    cards: [
      { id: 'mcp_servers', title: 'Connected MCP servers', adminOnly: true, Card: lazy(() => import('./McpServersCard')) },
    ],
  },
] satisfies SettingsSection[];
