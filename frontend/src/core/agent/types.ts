/**
 * Shapes of the /api/agent and memory routes. The routes return plain dicts, so the generated
 * OpenAPI types carry no response schema for them; these mirror backend/core/agent/router.py
 * and backend/core/memory/router.py.
 */

export interface ProviderInfo {
  provider: string;
  has_key: boolean;
  enabled: boolean;
  model_default: string;
  model_light: string;
  updated_at: string | null;
}

/** GET /api/agent/status */
export interface AgentStatus {
  configured: boolean;
  default_agent: string;
  providers: ProviderInfo[];
  models: { default: string | null; light: string | null };
}

export interface Conversation {
  id: number;
  user_id: number;
  agent_id: number;
  agent_slug: string;
  title: string;
  is_private: boolean;
  created_at: string;
  updated_at: string;
  compacted_at: string | null;
}

/** A tool-run row's status (agent.md §7), plus `running` while the call streams. */
export type ToolStatus =
  | 'running' | 'pending' | 'executing' | 'done' | 'denied' | 'error' | 'stale' | 'uncertain' | 'interrupted';

export interface ServerToolCall {
  tool: string;
  tool_use_id: string;
  args: Record<string, unknown>;
  tool_run_id: number | null;
  status: ToolStatus | null;
  result: unknown;
  error: string | null;
}

export interface ServerMessage {
  id: number;
  role: string;
  text: string;
  model: string | null;
  created_at: string;
  tool_calls: ServerToolCall[];
}

/** GET /api/agent/conversations/{id} */
export interface ConversationDetail extends Conversation {
  messages: ServerMessage[];
}

export interface AgentRow {
  id: number;
  slug: string;
  name: string;
  personality: string;
  provider_override: string | null;
  model_override: string | null;
  model_tier: 'default' | 'light';
  is_default: boolean;
  created_at: string;
}

/** One `data:` frame of POST /api/agent/chat. */
export type ChatEvent =
  | { type: 'conversation_id'; id: number }
  | { type: 'title_update'; conversation_id: number; title: string }
  | { type: 'compacted'; conversation_id?: number }
  | { type: 'text'; text: string }
  | { type: 'tool_start'; tool: string; tool_use_id: string }
  | { type: 'tool_args'; tool: string; tool_use_id: string; args: Record<string, unknown>; description: string }
  | { type: 'tool_end'; tool: string; tool_use_id: string; tool_run_id: number; status: ToolStatus; result: unknown; elapsed_ms: number }
  | { type: 'usage'; input_tokens: number; output_tokens: number; context_tokens: number; context_window: number }
  | { type: 'confirm'; tool_run_id: number; tool: string; tool_use_id: string; msg_id: number | null; args: Record<string, unknown>; description: string }
  | { type: 'done'; model: string }
  | { type: 'error'; error: string };

/** POST /api/agent/confirm */
export type ConfirmOutcome = 'done' | 'error' | 'uncertain' | 'stale' | 'denied' | 'already_resolved';
export interface ConfirmResponse {
  status: ConfirmOutcome;
  result?: unknown;
  error?: string;
  /** With `already_resolved`: the run's status now. */
  current?: ToolStatus;
}

/** GET /api/core/context-files */
export interface ContextFileMeta {
  filename: string;
  is_protected: boolean;
  updated_at: string | null;
  updated_by: number | null;
  size_chars: number;
  can_read: boolean;
  can_edit: boolean;
}

export interface ContextFile extends ContextFileMeta {
  content: string;
}

/** GET /api/core/memory/facts (admins also receive the provenance fields). */
export interface Fact {
  id: number;
  text: string;
  tags: string[];
  valid_from: string;
  invalid_from: string | null;
  source_conversation_id?: number | null;
  author_user_id?: number | null;
  author_name?: string | null;
  created_at?: string;
  invalidated_by?: number | null;
  superseded_by?: number | null;
}
