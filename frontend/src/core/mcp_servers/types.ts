import type { components } from '../api/types.gen';

type S = components['schemas'];

/** One remote tool as the last discovery found it. `read_only_hint` is the server's claim, shown only. */
export type RemoteTool = S['RemoteTool'];
/** GET /api/core/mcp/servers item. The token is write-only: only `has_token` comes back. */
export type McpServer = S['McpServer'];
/** POST /api/core/mcp/servers/{id}/test */
export type McpServerCheck = S['McpServerCheck'];

export interface ServerDraft {
  name: string;
  url: string;
  token: string;
  prefix: string;
}
