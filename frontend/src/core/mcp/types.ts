/** GET /api/core/mcp/links: the caller's live links. Never carries the token. */
export interface McpLink {
  id: number;
  label: string;
  created_at: string;
  last_used_at: string | null;
}

/** POST /api/core/mcp/links: the only response that carries the token and its URL. */
export interface NewMcpLink extends McpLink {
  url: string;
  token: string;
}
