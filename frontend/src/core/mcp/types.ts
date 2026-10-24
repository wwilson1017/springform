import type { components } from '../api/types.gen';

type S = components['schemas'];

/** GET /api/core/mcp/links: the caller's live links. Never carries the token. */
export type McpLink = S['McpLink'];
/** POST /api/core/mcp/links: the only response that carries the token and its URL. */
export type NewMcpLink = S['NewMcpLink'];
