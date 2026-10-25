/**
 * Shapes of the /api/agent and memory routes. Response shapes are the generated schemas; the chat
 * stream's frames, context files and facts keep hand-written shapes (no response model).
 */
import type { components } from '../api/types.gen';

type S = components['schemas'];

export type ProviderInfo = S['ProviderInfo'];
/** GET /api/agent/status */
export type AgentStatus = S['AgentStatus'];
export type Conversation = S['Conversation'];
/** A tool-run row's status (agent.md §7), plus `running` while the call streams. */
export type ToolStatus = NonNullable<ServerToolCall['status']> | 'running';
export type ServerToolCall = S['ServerToolCall'];
export type ServerMessage = S['ServerMessage'];
/** GET /api/agent/conversations/{id} */
export type ConversationDetail = S['ConversationDetail'];
export type AgentRow = S['AgentRow'];
/** POST /api/agent/providers/{provider}/test */
export type ProviderTest = S['ProviderTest'];

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

/** POST /api/agent/confirm. With `already_resolved`, `current` is the run's status now. */
export type ConfirmResponse = S['ConfirmResponse'];
export type ConfirmOutcome = ConfirmResponse['status'];

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
