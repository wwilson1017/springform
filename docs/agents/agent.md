# Whisk, the agent

**What this covers:** all of §5: modules and their sources, tables, memory and privacy rules, the `ToolSpec` contract and both handler forms, `targets`, `build_registry` validations, `for_user` / `for_source`, `tool_def_sha256`, the turn loop, server-side confirmation steps (a)–(d), the tool-run status enum, SSE events, zero-key behaviour, the default soul, and the frontend pieces.
**Who reads it:** W9 (providers, `ToolSpec`, registry, confirm tiers, core tool sources), W12 (engine, history, compaction, confirm, router, chat UI), W14/W15 (MCP), W16 (observer/dreaming), and every app writing `tools.py`.

Code: the engine is `backend/core/agent/`; memory, context files, the observer, dreaming and the nightly job are the `backend/core/memory/` package. One default agent, **Whisk**, roster-capable.

## 1. Modules and sources

Base: CakeCRM `backend/assistant/` (Chatty's loop already trimmed, with server-side confirmation) + CakeCRM `backend/providers/` (lazy SDK imports, zero-key start) + CakeCRM `backend/memory/` (Chatty's memory as CakeCRM ported it) + Chatty `deferred_tools.py` and context-file layout.

| Module | Source | Lines |
|---|---|---|
| `providers/` | CakeCRM `providers/`, Anthropic and OpenAI only; `credentials.py` rewritten so keys and the default and light models live only in `core_agent_providers` rows; `fake.py` (FakeProvider) and `windows.py` new | about 590 |
| `spec.py`, `registry.py` | CakeCRM `assistant/registry.py` (212); sources = core + discovered apps + MCP servers; atomic swap on refresh | 150 / 160 new |
| `engine.py`, `history.py`, `assembly.py`, `compaction.py`, `delimiters.py`, `write_budget.py`, `llm.py` | CakeCRM `assistant/` (its `confirm_tier.py` folded into `spec.py` as the `ROUTINE` constant); JSONB → TEXT, array ops in Python; Gmail/page bindings cut; `turns.py` skipped in v1 | ~2,500 |
| `deferred.py` | Chatty `deferred_tools.py`; group key = app slug, threshold 100 | 350 |
| `agents.py` | CakeCRM `assistant/identity.py` prompt builder; agents are rows, not a singleton | 300 |
| `backend/core/memory/facts.py`, `context_files.py`, `tools.py`, `router.py` | `facts.py` from CakeCRM `backend/memory/service.py` (FTS5, temporal facts, soft invalidation); `context_files.py` from CakeCRM `backend/context_files/service.py`, tsvector → FTS5 | 1,800 |
| `backend/core/memory/observer.py`, `dreaming.py`, `jobs.py` | The observer from Chatty plus CakeCRM `backend/memory/observer.py`; dreaming is new, plain Python with no model call (it merges duplicate facts); nightly and setting-gated | 580 |
| `router.py`; the inbound server `backend/core/mcp/` and the outbound client `backend/core/mcp_servers/` (landing with the MCP workstream) | CakeCRM `assistant/router.py` and `providers/router.py`, minus uploads; new; new | 250 / 250 / 320 |

Inbound MCP landed as its own core package, `backend/core/mcp/` (`mcp.md` §1), not `agent/mcp_server.py`. `execute.py` (`run_tool(user, spec, args, *, source)`) is the one path that runs a tool call and records its tool run: the turn loop's ungated calls, `confirm` (which passes the pending run's id to claim it), and inbound MCP.

## 2. Tables

```sql
core_agents(slug UNIQUE, name, personality, provider_override, model_override, model_tier, is_default, created_at)
  -- seeded: whisk. No soul column: personality is the admin's extra instructions ('' = none);
  -- the soul is the agent's soul.md context file (§10)
core_agent_conversations(user_id NOT NULL, agent_id, title, is_private DEFAULT 0, summary, summary_first_kept_id,
                         last_context_tokens, tainted DEFAULT 0, created_at, updated_at, compacted_at)
core_agent_messages            -- + FTS
core_agent_tool_runs(
  id, conversation_id, message_id, tool_use_id, tool, tool_def_sha256,
  args JSON DEFAULT '{}',
  status,                      -- CHECK over the eight values in §7
  result, error, user_id,
  source CHECK (source IN ('chat','mcp','job')),
  requested_at, resolved_at, resolved_by
)                              -- the pending store and the audit log
core_agent_facts(text, tags JSON, valid_from, invalid_from, invalidated_by, superseded_by,
                 source_conversation_id, author_user_id, created_at)   -- + FTS
core_agent_observations(conversation_id PK, through_message_id, pending, marked_at, observed_at, facts_added)
  -- the observer's per-conversation ledger
core_agent_context_files(agent_slug, filename COLLATE NOCASE, content, is_protected, updated_at, updated_by)
  -- UNIQUE(agent_slug, filename); agent_slug matches core_agents.slug by value; + FTS
core_agent_providers(provider PK, api_key_enc, model_default, model_light, enabled, updated_at)
core_agent_mcp_links           -- mcp.md; not built yet
core_agent_mcp_servers         -- mcp.md §2
```

Memory search is FTS5 only; there is no vector table.

## 3. Memory and privacy (decided)

1. Memory, facts, observations and context files are **install-shared business memory**.
2. Conversations are **private to their user**: a `user_id` filter on every read, including FTS.
3. `observer.py` extracts business facts only, from conversations **not** marked `is_private`, under a prompt that forbids personal details about members.
4. Extracted facts carry provenance: `source_conversation_id` and date. The observer writes them as the system principal (`author_user_id = 0`) tagged `observed`, so the member is traceable only through the conversation id.
5. **An admin sees that provenance metadata and can "delete" the fact; nobody but its user can read the conversation itself.** Deleting a fact ends its validity (`invalid_from`, `invalidated_by`); the row and its text stay, and an admin's history search still finds it.
6. Context files are admin-edited. `is_protected` files (soul, MEMORY) are writable **only through a confirmed chat tool by an admin**, never through MCP or jobs.
7. Unattended runs (`source='job'`) run as the **system principal** (`core_users.id=0`, role `system`, member-level reads only, no private records, cannot authenticate) and may only call tools that are `writes=False`, not `always_confirm`, not remote, and not `untrusted_source`. **Enforced in `registry.for_source`, not by convention.**

## 4. Tool contract

```python
ToolSpec(
    name, description, input_schema,
    writes,             # bool
    confirm_tier,       # only when writes
    always_confirm,     # forces confirmation, even for reads (remote tools set it)
    hides_when,         # Callable[[dict], bool] | None, called with the args
    handler | handler_in,
    targets,            # targets(args) -> list[(entity_type, id)]
    enabled,            # enabled(user) -> bool
    untrusted_source,   # results fenced as untrusted (remote tools)
    external_effect: bool = False,   # acts outside the install (remote MCP, email, HTTP); run per §6 rule 1
    mcp_exposed: bool = True,
    app,                # owning app slug, or core
    revision,           # the owning app's version string; "" for core tools
    server_id, server_url,   # remote (outbound MCP) tools only; remote means server_url is set
)
```

### Handler forms

| Form | Signature | Use | Runs |
|---|---|---|---|
| `handler_in` | `handler_in(conn, user, args)` | **Local writes.** | Inside the approval transaction. Must use `_in` service functions, never `transaction()`. |
| `handler` | `handler(user, args)` | Reads and external-effect tools. | Outside any transaction. |

### `targets`

`targets(args) -> list[(entity_type, id)]` names **every** record the call touches, including bulk operations. The engine calls `entities.authorize(user, conn, …, "write")` on each, inside the same transaction, before `handler_in` runs.

### `confirm_tier`

`confirm_tier` has one legal value, `"routine"` (the `ROUTINE` constant in `spec.py`, from CakeCRM's `assistant/confirm_tier.py`): a write that carries it may skip the Approve card, and absence means the write confirms.

### Validation at `build_registry()` (fails boot)

1. Names are unique.
2. Names carry the `<slug>_` prefix (app tools; the contract test checks it too). Core tools are prefixed `core_`.
3. `writes` is a `bool`.
4. `confirm_tier` is allowed only when `writes`.
5. A write tool has `handler_in` **and** `targets`, or is marked `external_effect`.
6. `always_confirm` is allowed on any spec.
7. A name is 1 to 64 characters of `[a-zA-Z0-9_-]`.
8. `input_schema` is a JSON schema of type `object`.
9. A spec gives exactly one of `handler` and `handler_in`.
10. An `external_effect` tool runs through `handler`; a read runs through `handler`, never `handler_in`.

`hides_when(args)` puts the Approve card back on a routine write whose args would take a record out of view. It confirms when it returns true, and also when it raises (it fails closed).

`mcp_exposed=False` removes a tool from `for_source("mcp")`; the protected context-file write tool sets it.

### Filtering

| Call | Returns |
|---|---|
| `registry.for_user(user)` | Specs where `enabled(user)` is true and the user has one of the owning app's roles. |
| `registry.for_source("mcp")` | Excludes protected context-file writes and remote (outbound) tools; admin-only tools are already filtered by role (`mcp.md`). |
| `registry.for_source("job")` | Only `writes=False`, not `always_confirm`, not remote, not `untrusted_source`. |

### `tool_def_sha256`

Hash of:

1. `name`;
2. `description`;
3. `input_schema`;
4. `writes`;
5. `confirm_tier`;
6. `always_confirm`;
7. `revision`: the app's manifest `version`, or `""` for core tools;
8. `server_id` and `server_url`: the remote server for remote tools, null for local ones.

So a pending approval is bound to exactly what was shown, where it will run, and the implementation revision.

The hash is the sha256 hex of `json.dumps(fields, sort_keys=True)` over the fields above.

### Registry sources and refresh

Sources: core packages' `tools.py` (context files, memory; `apps-and-contracts.md` §9), discovered apps' `get_tools()`, and MCP servers (`mcp.md`). Outbound MCP servers are the one source that changes after boot: `registry.swap_server(server_id, specs)` replaces one server's specs, rebuilds and validates the whole registry, and **swaps it in atomically** (a refused build changes nothing). Old specs stay valid for already-pending approvals only until their `tool_def_sha256` check fails. `build_registry` also refuses a remote spec (`server_url` set) that is not `always_confirm`, `untrusted_source` and `external_effect`.

Deferred tools (`deferred.py`): groups keyed by app slug, deferral threshold 100 tools.

## 5. Turn loop

CakeCRM's loop, minus Google/Odoo/QuickBooks/todo/meeting logic, plan mode, LLM smart titles, GCS, and Chatty's `/tool/execute`.

1. Compaction at **70%** of the context window, via the light model tier.
2. Reads run immediately through `handler(user, args)`.
3. A call confirms when the tool is `always_confirm`, or when it is a write that is not routine, is `external_effect`, runs in a tainted conversation, or whose `hides_when(args)` is true or raises. A confirming call inserts a `pending` tool run and emits `confirm`; the client continues by posting `/api/agent/chat` with the conversation id and no message.
4. Results from `untrusted_source` tools are fenced with `delimiters.wrap_untrusted_external` and taint the **conversation** (`core_agent_conversations.tainted`), permanently and across compaction: every later write in it confirms, routine ones included.

## 6. Server-side confirmation

`POST /api/agent/confirm`:

| Step | Check |
|---|---|
| (a) | Re-authenticate the approver and require them to **own the conversation**. A non-owner gets 403. |
| (b) | Re-run `enabled(user)`. |
| (c) | Check `tool_def_sha256` still matches the live registry; else status **`stale`**, shown to the user. |
| (d) | Inside **one** `transaction()`: claim the row (`UPDATE … SET status='executing' WHERE id=? AND status='pending'`), authorize every `targets(args)` record for write, run `handler_in` with the args **from the DB** (never from the request), write `done` + result. All committed atomically. |

Further rules:

1. **Handler-form tools** (external effects such as remote MCP, email and HTTP, and reads that always confirm) are claimed in one transaction, executed outside it, and resolved in another. Any failure of an `external_effect` handler, a timeout included, marks `uncertain` with the error shown to the user, since the effect may have happened; a failing handler without `external_effect` records `error`.
2. On startup, rows left `executing` are marked `interrupted` and surfaced in the conversation.
3. A double approve returns **`already_resolved`**; the tool runs once.
4. A deny is recorded (`denied`, `resolved_by`, `resolved_at`).
5. A call through an MCP link (`source='mcp'`) skips this confirmation: it executes immediately as the link's user and is logged in `core_agent_tool_runs` (`mcp.md` §1).

`POST /api/agent/confirm {tool_run_id, decision: "approve" | "deny"}` answers **200** with `{status, result?, error?}`. `status` is one of `done`, `error`, `uncertain`, `stale`, `denied` or `already_resolved`; `already_resolved` comes with `current`, the run's actual status. `already_resolved` is a response status, never a row status. A missing run, or one that is not a chat run, is 404, and a conversation the caller does not own is 403 `not_your_conversation`.

## 7. Tool-run status enum

```
pending | executing | done | denied | error | stale | uncertain | interrupted
```

`core_agent_tool_runs.status` takes exactly these eight values; the table's `CHECK` lists all eight, `stale` included. `already_resolved` is only a response status of `POST /api/agent/confirm` (§6).

## 8. SSE events

The chat stream emits these event types:

```
conversation_id, compacted, text, tool_start, tool_args, tool_end, usage, confirm, title_update, done, error
```

| Event | Payload |
|---|---|
| `conversation_id` | `{id}` |
| `title_update` | `{conversation_id, title}` |
| `compacted` | `{conversation_id}` |
| `text` | `{text}` |
| `tool_start` | `{tool, tool_use_id}` |
| `tool_args` | `{tool, tool_use_id, args, description}` |
| `tool_end` | `{tool, tool_use_id, tool_run_id, status, result, elapsed_ms}` |
| `usage` | `{input_tokens, output_tokens, context_tokens, context_window}` |
| `confirm` | `{tool_run_id, tool, tool_use_id, msg_id, args, description}` |
| `done` | `{model}` |
| `error` | `{error}` |

## 9. Zero keys

1. `GET /api/agent/status` → `{configured: false}`.
2. `POST /api/agent/chat` returns **400** `{detail: "no_provider"}`.
3. The Whisk page shows the card with an admin link to Settings → AI.
4. The registry and inbound MCP still work.
5. The nightly job `core.agent_nightly` has no up-front key check. It is skipped (`no_provider`) when the observer reaches a model call; otherwise it finishes `ok` and dreaming, which uses no model, still runs. The CRM's `crm.touch_count` LLM work is skipped too.

## 10. Default `soul.md`

`soul.md` is a protected context file of each agent (`core_agent_context_files`, keyed by `agent_slug`), with its default text in `backend/core/memory/context_files.py`. It is the only soul: the agent row has no soul column. The default says Whisk is the business assistant for this install; knows the installed apps, the contacts directory and each app's records; answers from them, says what it changed, proposes a write before making it; plain-spoken, brief, careful with anything that leaves the install or hides a record.

## 11. Routes

| Route | Contract |
|---|---|
| `GET /api/agent/status` | `{configured, default_agent, providers, models: {default, light}}`. |
| `POST /api/agent/chat` | The SSE stream of one turn. Body `{conversation_id?, agent_slug?, message?}`; no message plus a `conversation_id` continues after an approval. 422 when both are missing, 404 `conversation_not_found`, 400 `{detail: "no_provider"}` with zero keys. |
| `POST /api/agent/confirm` | §6. |
| `GET` / `POST /api/agent/conversations`; `GET` / `PATCH {title, is_private}` / `DELETE /api/agent/conversations/{id}` | The caller's own conversations only. |
| `GET /api/agent/agents`; `PATCH /api/agent/agents/{slug}` (admin) | The PATCH takes `name`, `personality`, `provider_override` (`anthropic` or `openai`), `model_override` and `model_tier` (`default` or `light`). |
| `GET /api/agent/providers`, `PUT /api/agent/providers/{provider}`, `POST /api/agent/providers/{provider}/test` (admin) | Provider keys and default and light models, one `core_agent_providers` row per vendor. |
| `GET /api/core/context-files[?agent=<slug>]`, `GET` / `PUT /api/core/context-files/{filename}[?agent=<slug>]` | Context files per agent (default `whisk`). Members list them and read the unprotected ones; admins read all and write through `PUT`. Protected files (`soul.md`, `MEMORY.md`) refuse the REST editor: they change only through the confirmed chat tool. |
| `GET /api/core/memory/facts[?q=&limit=&offset=&history=]`, `POST /api/core/memory/facts {text, tags, valid_from?}`, `DELETE /api/core/memory/facts/{id}` (admin) | Install-shared facts, not per agent. Admins see provenance, and `history=true` (admins only) adds ended facts. `DELETE` ends the fact's validity (§3). |
| MCP links | `GET` / `POST /api/core/mcp/links`, `DELETE /api/core/mcp/links/{id}` (`mcp.md` §1). |
| MCP servers | `/api/core/mcp/servers` (admin; `mcp.md` §2), not under `/api/agent`. |

The routes under `/api/agent` are in `backend/core/agent/router.py`; the memory routes are in `backend/core/memory/router.py`.

## 12. Jobs

`core.agent_nightly` at 02:00 (timeout 1,800 s), gated by the setting `agent.nightly_enabled`: the observer, then dreaming. With zero keys it is skipped only when the observer reaches a model call (§9). See `scheduler.md`.

## 13. Step 1 stub

Step 1 ships `agent/spec.py` + `registry.py` + a **FakeProvider** engine stub that can run one confirmed `handler_in` tool. Step 1b's slice runs a FakeProvider tool call that confirms and runs via `handler_in`.

## 14. Frontend (`frontend/src/core/agent/`)

| Piece | Source | What it does |
|---|---|---|
| `WhiskPage` | Chatty `agent/AgentPage.tsx` | `/whisk/*` (one splat route, lazy): conversation list beside the chat; `/whisk/<id>` opens a thread, another user's id answers 404 and shows "not found". |
| `AgentChatPanel` | Chatty `AgentChatPanel.tsx` | Messages, composer (Enter sends, Shift+Enter adds a line, Stop while streaming), context meter from `usage`. |
| `useAgentChat`, `chatModel`, `sse` | Chatty `useAgentChat.ts` | POST /chat read as SSE over `fetch`; an assistant message is ordered text and tool parts, so a reloaded thread (consecutive assistant rows merged) looks like the streamed one. |
| `AgentMessageBubble` | Chatty `AgentMessageBubble.tsx` | Markdown text, collapsible tool calls (args, result, status), compaction note, stream errors. |
| `ToolConfirmCard`, `confirmState` | Chatty card, CakeCRM resolve rule | The Approve card: tool, description, full args. `pending → sending → resolved`; a failed request returns to pending. Each of `done`, `error`, `uncertain`, `stale`, `denied`, `already_resolved` has its own words. |
| `ConversationSidebar`, `useConversations` | Chatty | Search (`?q=` over message text), new, inline rename, private toggle, delete with confirm. |
| `MarkdownContent` | shared with the Guide (`src/shared/`) | GFM, no highlighting; in-app links stay in the tab through `Link`, external ones open a new tab; images never load. |
| `ZeroKeyCard` | new | `status.configured:false`: replaces the composer; admins get a link to Settings, AI, members are told to ask an admin. Old threads still open. |
| `settingsCards.ts`, section `ai` (admin, order 70) | CakeCRM `ProviderSetup` (Providers), Chatty `AgentContextEditor` (Memory) | Providers (key set/replace/remove via `has_key`, both model tiers, enabled, Test), Agents (name, personality, provider and model override, tier), Memory (context files with protected ones read-only; facts with provenance and "End validity"), Nightly run (`agent.nightly_enabled`). |
| MCP links card, MCP servers card | new | Not built yet (`mcp.md`). |

Rules the frontend keeps:

1. **Resume after approval.** Once every card of a message has resolved, the client posts `/chat {conversation_id}` with no message, so the model hears every outcome, a deny included. It does not resume when every answer was `already_resolved` (another tab decided).
2. **Reconnection.** The engine runs a turn inside its response, so a dropped stream cannot be re-attached. A stream that errors or ends without `done`/`error` makes the client re-read `GET /conversations/{id}` with backoff (0.5 s doubling to 8 s) and show what was saved, pending cards included. Stop aborts and re-reads once.
3. A `confirm` event has no `tool_end`; the call's part becomes the card (status `pending`).
4. A 400 `no_provider` from `/chat` re-reads `/status`, which brings up the zero-key card.
5. The shared dialog host is `frontend/src/shared/ConfirmHost.tsx`, lifted from CakeCRM; it is not an agent piece (the Approve card is `ToolConfirmCard`).

## Tests that pin this

- Registry rejects duplicate/unprefixed/tier-on-read specs; `for_source("job")` excludes writes; `for_source("mcp")` excludes protected and remote tools.
- Zero-key status + 400.
- FakeProvider streams text + a write tool → `confirm`, pending run, approve by a non-owner 403, stale `tool_def_sha256` → `stale`, approve executes once with args from the DB (double approve = `already_resolved`), deny recorded, `executing` at startup → `interrupted`.
- No network or LLM call inside `transaction()`.
- Playwright: Whisk answers with FakeProvider → write tool shows Approve and runs on approve → zero-key card.

## Source

Build plan: §5 (all), §2 (system principal), §6 (exclusions, remote specs), §11 (the nightly agent job), Decisions (Agent), Step 1, Step 2 W9, Step 3 W12, Step 4 W14–W16, Risks 5 and 8, Verification.
