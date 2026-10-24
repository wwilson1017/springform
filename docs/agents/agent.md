# Whisk, the agent

**What this covers:** all of §5: modules and their sources, tables, memory and privacy rules, the `ToolSpec` contract and both handler forms, `targets`, `build_registry` validations, `for_user` / `for_source`, `tool_def_sha256`, the turn loop, server-side confirmation steps (a)–(d), the tool-run status enum, SSE events, zero-key behaviour, the default soul, and the frontend pieces.
**Who reads it:** W9 (providers, `ToolSpec`, registry, confirm tiers, core tool sources), W12 (engine, history, compaction, confirm, router, chat UI), W14/W15 (MCP), W16 (observer/dreaming), and every app writing `tools.py`.

Code: `backend/core/agent/`. One default agent, **Whisk**, roster-capable.

## 1. Modules and sources

Base: CakeCRM `backend/assistant/` (Chatty's loop already trimmed, with server-side confirmation) + CakeCRM `backend/providers/` (lazy SDK imports, zero-key start) + Chatty `backend/core/agents/memory/db.py`, `deferred_tools.py` and context-file layout.

| Module | Source | Lines |
|---|---|---|
| `providers/` | CakeCRM `providers/` whole; `credentials.py` → `core_agent_providers` + settings | 2,400 lifted / 200 ported |
| `spec.py`, `registry.py` | CakeCRM `assistant/registry.py` (212); sources = core + discovered apps + MCP servers; atomic swap on refresh | 150 / 160 new |
| `confirm_tier.py`, `engine.py`, `history.py`, `assembly.py`, `compaction.py`, `delimiters.py`, `write_budget.py` | CakeCRM `assistant/`; JSONB → TEXT, array ops in Python; Gmail/page bindings cut; `turns.py` skipped in v1 | ~2,500 |
| `deferred.py` | Chatty `deferred_tools.py`; group key = app slug, threshold 100 | 350 |
| `agents.py` | CakeCRM `assistant/identity.py` prompt builder; agents are rows, not a singleton | 300 |
| `memory/`, `context_files/` | Chatty memory (FTS5, temporal facts, observations; drop GCS, brain, commitments); CakeCRM `context_files/` with tsvector → FTS5 | 1,800 |
| `observer.py`, `dreaming.py`, `jobs.py` | Chatty; nightly, setting-gated, skipped with zero keys | 580 |
| `router.py`, `mcp_server.py`, `mcp_client.py` | CakeCRM `assistant/router.py` minus uploads; new; new | 250 / 250 / 320 |

`delimiters.py` and `write_budget.py` are in the lift list but not drawn in the plan's repo tree.

Inbound MCP landed as its own core package, `backend/core/mcp/` (`mcp.md` §1), not `agent/mcp_server.py`. `execute.py` (`run_tool(user, spec, args, *, source)`) is the one path that runs a tool call and records its tool run: the turn loop's ungated calls, `confirm` (which passes the pending run's id to claim it), and inbound MCP.

## 2. Tables

```sql
core_agents(slug UNIQUE, name, personality, provider_override, model_override, model_tier, is_default)
  -- seeded: whisk
core_agent_conversations(user_id NOT NULL, is_private DEFAULT 0, …)
core_agent_messages            -- + FTS
core_agent_tool_runs(
  id, conversation_id, tool_use_id, tool, tool_def_sha256,
  args JSON,
  status,                      -- CHECK over the eight values in §7
  result, user_id,
  source CHECK (source IN ('chat','mcp','job')),
  requested_at, resolved_at, resolved_by
)                              -- the pending store and the audit log
core_agent_memory_*            -- Chatty memory tables
core_agent_facts
core_agent_observations
core_agent_vectors             -- optional, only with AGENT_VECTOR=1
core_agent_context_files(agent_id, filename, content, is_protected, …)   -- + FTS
core_agent_providers
core_agent_mcp_links           -- mcp.md
core_agent_mcp_servers         -- mcp.md
```

Open (pinned by the implementing workstream, which updates this doc): the `core_agent_memory_*` table set and the facts/observations columns (beyond the provenance fields in §3) are not listed; lift Chatty's shape with the `core_agent_` prefix.

## 3. Memory and privacy (decided)

1. Memory, facts, observations and context files are **install-shared business memory**.
2. Conversations are **private to their user**: a `user_id` filter on every read, including FTS.
3. `observer.py` extracts business facts only, from conversations **not** marked `is_private`, under a prompt that forbids personal details about members.
4. Extracted facts carry provenance: `source_conversation_id`, date, author user id.
5. **An admin sees that provenance metadata and can delete the fact; nobody but its user can read the conversation itself.**
6. Context files are admin-edited. `is_protected` files (soul, MEMORY) are writable **only through a confirmed chat tool by an admin**, never through MCP or jobs.
7. Unattended runs (`source='job'`) run as the **system principal** (`core_users.id=0`, role `system`, member-level reads only, no private records, cannot authenticate) and may only call tools that are `writes=False`, not `always_confirm`, not remote, and not `untrusted_source`. **Enforced in `registry.for_source`, not by convention.**

## 4. Tool contract

```python
ToolSpec(
    name, description, input_schema,
    writes,             # bool
    confirm_tier,       # only when writes
    always_confirm,     # forces confirmation, even for reads (remote tools set it)
    hides_when,         # Callable[[User], bool] | None
    handler | handler_in,
    targets,            # targets(args) -> list[(entity_type, id)]
    enabled,            # enabled(user) -> bool
    untrusted_source,   # results fenced as untrusted (remote tools)
    external_effect: bool = False,   # acts outside the install (remote MCP, email, HTTP); run per §6 rule 1
    mcp_exposed: bool = True,
    app,                # owning app slug, or core
    revision,           # the owning app's version string
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

In the CakeCRM donor (`assistant/confirm_tier.py`), `confirm_tier` has one legal value, `"routine"`: a write that carries it skips the Approve card in normal mode, and absence means the write confirms. The plan lifts that module.

### Validation at `build_registry()` (fails boot)

1. Names are unique.
2. Names carry the `<slug>_` prefix (app tools; the contract test checks it too). Core tools are prefixed `core_`.
3. `writes` is a `bool`.
4. `confirm_tier` is allowed only when `writes`.
5. A write tool has `handler_in` **and** `targets`, or is marked `external_effect`.
6. `always_confirm` is allowed on any spec.

Open (pinned by the implementing workstream, which updates this doc): what `hides_when` hides, beside `enabled`, and whether `mcp_exposed=False` removes a tool from `for_source("mcp")` (the natural reading).

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
7. the app's manifest `version`, or the core version for core tools;
8. for remote tools, the server id **and URL**.

So a pending approval is bound to exactly what was shown, where it will run, and the implementation revision.

The hash is the sha256 of `json.dumps(fields, sort_keys=True)` over the fields above.

### Registry sources and refresh

Sources: core packages' `tools.py` (context files, memory; `apps-and-contracts.md` §9), discovered apps' `get_tools()`, and MCP servers (`mcp.md`). A refresh builds a new registry and **swaps it in atomically**. Old specs stay valid for already-pending approvals only until their `tool_def_sha256` check fails.

Deferred tools (`deferred.py`): groups keyed by app slug, deferral threshold 100 tools.

## 5. Turn loop

CakeCRM's loop, minus Google/Odoo/QuickBooks/todo/meeting logic, plan mode, LLM smart titles, GCS, and Chatty's `/tool/execute`.

1. Compaction at **70%** of the context window, via the light model tier.
2. Reads run immediately through `handler(user, args)`.
3. A **gated** write (any write without the routine tier, or any `always_confirm` tool) inserts a `pending` tool run and emits `confirm {tool_run_id, tool, args}`.
4. Results from `untrusted_source` tools are fenced with `delimiters.wrap_untrusted_external` and taint the turn.

## 6. Server-side confirmation

`POST /api/agent/confirm`:

| Step | Check |
|---|---|
| (a) | Re-authenticate the approver and require them to **own the conversation**. A non-owner gets 403. |
| (b) | Re-run `enabled(user)`. |
| (c) | Check `tool_def_sha256` still matches the live registry; else status **`stale`**, shown to the user. |
| (d) | Inside **one** `transaction()`: claim the row (`UPDATE … SET status='executing' WHERE id=? AND status='pending'`), authorize every `targets(args)` record for write, run `handler_in` with the args **from the DB** (never from the request), write `done` + result. All committed atomically. |

Further rules:

1. **External-effect tools** (remote MCP, email, HTTP) are claimed in one transaction, executed outside it, and resolved in another. A timeout marks `uncertain` with the error shown to the user.
2. On startup, rows left `executing` are marked `interrupted` and surfaced in the conversation.
3. A double approve returns **`already_resolved`**; the tool runs once.
4. A deny is recorded (`denied`, `resolved_by`, `resolved_at`).

`POST /api/agent/confirm {tool_run_id, decision: "approve" | "deny"}` returns `{status, result?}`. `already_resolved` is a response status, never a row status.

Open (pinned by the implementing workstream, which updates this doc): the HTTP status code that accompanies `stale` and `already_resolved`.

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

`confirm` carries `{tool_run_id, tool, args}`.

Open (pinned by the implementing workstream, which updates this doc): the other events' payload shapes (lifted from CakeCRM) are not restated in the plan.

## 9. Zero keys

1. `GET /api/agent/status` → `{configured: false}`.
2. Chat returns **400** "add a key".
3. The Whisk page shows the card with an admin link to Settings → AI.
4. The registry and inbound MCP still work.
5. The nightly job `core.agent_nightly` (observer, dreaming) exits early. The CRM's `crm.touch_count` LLM work is skipped too.

## 10. Default `soul.md`

Whisk is the business assistant for this install; knows the installed apps, the contacts directory and each app's records; answers from them, says what it changed, proposes a write before making it; plain-spoken, brief, careful with anything that leaves the install or hides a record.

## 11. Routes

| Route | Contract |
|---|---|
| `GET /api/agent/status` | `{configured: bool, …}`. |
| `POST /api/agent/confirm` | §6. |
| Chat (SSE), conversations, context files, providers/keys, MCP servers | Under `/api/agent/...`; shape to be pinned by W9/W12/W15. |
| MCP links | `/api/core/mcp/links` (`mcp.md` §1). |

## 12. Jobs

`core.agent_nightly` at 02:00, gated by the setting `agent.nightly_enabled`, skipped with zero keys (observer + dreaming). See `scheduler.md`.

## 13. Step 1 stub

Step 1 ships `agent/spec.py` + `registry.py` + a **FakeProvider** engine stub that can run one confirmed `handler_in` tool. Step 1b's slice runs a FakeProvider tool call that confirms and runs via `handler_in`.

## 14. Frontend (`frontend/src/core/agent/`)

| Piece | Source | Target size |
|---|---|---|
| `WhiskPage` | Chatty `agent/AgentPage.tsx` (967) | ~400 |
| `AgentChatPanel` | Chatty `agent/components/AgentChatPanel.tsx` (880) | ~500 |
| `useAgentChat` | Chatty `agent/hooks/useAgentChat.ts` (653) | ~400 |
| `AgentMessageBubble` | Chatty `agent/components/AgentMessageBubble.tsx` (515) | ~350 |
| `ConversationSidebar` | Chatty `agent/components/ConversationSidebar.tsx` (273) | |
| `useConversations` | Chatty `agent/hooks/useConversations.ts` (197) | |
| `ConfirmHost` | Chatty `shared/ConfirmHost.tsx` (126) | |
| `MarkdownContent` | Chatty `agent/components/MarkdownContent.tsx` (94) | as is |
| `ContextFilesPage` | Chatty `agent/components/AgentContextEditor.tsx` (453) | |
| `ProviderSetup` + keys card | CakeCRM `setup/ProviderSetup.tsx` (129) | |
| MCP links card, MCP servers card | new | ~300 |

Chatty's inline styles move to Tailwind tokens (`--color-sf-*`), budgeted in W12. The Approve card shows full args.

## Tests that pin this

- Registry rejects duplicate/unprefixed/tier-on-read specs; `for_source("job")` excludes writes; `for_source("mcp")` excludes protected and remote tools.
- Zero-key status + 400.
- FakeProvider streams text + a write tool → `confirm`, pending run, approve by a non-owner 403, stale `tool_def_sha256` → `stale`, approve executes once with args from the DB (double approve = `already_resolved`), deny recorded, `executing` at startup → `interrupted`.
- No network or LLM call inside `transaction()`.
- Playwright: Whisk answers with FakeProvider → write tool shows Approve and runs on approve → zero-key card.

## Source

Build plan: §5 (all), §2 (system principal), §6 (exclusions, remote specs), §11 (the nightly agent job), Decisions (Agent), Step 1, Step 2 W9, Step 3 W12, Step 4 W14–W16, Risks 5 and 8, Verification.
