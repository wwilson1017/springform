/** One remote tool as the last discovery found it. `read_only_hint` is the server's claim, shown only. */
export interface RemoteTool {
  name: string;
  description: string;
  read_only_hint: boolean;
}

/** GET /api/core/mcp/servers item. The token is write-only: only `has_token` comes back. */
export interface McpServer {
  id: number;
  name: string;
  url: string;
  prefix: string;
  enabled: boolean;
  has_token: boolean;
  tools: RemoteTool[];
  last_discovered_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ServerDraft {
  name: string;
  url: string;
  token: string;
  prefix: string;
}
