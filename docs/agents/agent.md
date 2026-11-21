# Whisk, the agent

**What this covers:** all of §5: modules and their sources, tables, memory and privacy rules, the `ToolSpec` contract and both handler forms, `targets`, `build_registry` validations, `for_user` / `for_source`, `tool_def_sha256`, the turn loop, server-side confirmation steps (a)–(d), the tool-run status enum, SSE events, zero-key behaviour, the default soul, and the frontend pieces.
**Who reads it:** W9 (providers, `ToolSpec`, registry, confirm tiers, core tool sources), W12 (engine, history, compaction, confirm, router, chat UI), W14/W15 (MCP), W16 (observer/dreaming), and every app writing `tools.py`.

Code: the engine is `backend/core/agent/`; memory, context files, the observer, dreaming and the nightly job are the `backend/core/memory/` package. One default agent, **Whisk**, roster-capable.

## 1. Modules and sources

Base: CakeCRM `backend/assistant/` (Chatty's loop already trimmed, with server-side confirmation) + CakeCRM `backend/providers/` (lazy SDK imports, zero-key start) + CakeCRM `backend/memory/` (Chatty's memory as CakeCRM ported it) + Chatty `deferred_tools.py` and context-file layout.

| Module | Source | Lines (built) |
|---|---|---|
| `providers/` | CakeCRM `providers/` (`windows.py` included), Anthropic and OpenAI only; `credentials.py` rewritten so keys live only in `core_agent_providers` rows, with the default and light models taken from the row or, when it leaves them empty, from `DEFAULT_MODELS`; `fake.py` (FakeProvider, `AGENT_FAKE_PROVIDER=1`) new | 672 |
| `spec.py`, `registry.py` | CakeCRM `assistant/registry.py` (212); sources = core + discovered apps + MCP servers; atomic swap on refresh | 76 / 131 |
| `engine.py`, `history.py`, `assembly.py`, `compaction.py`, `delimiters.py`, `write_budget.py`, `llm.py` | CakeCRM `assistant/` (its `confirm_tier.py` folded into `spec.py` as the `ROUTINE` constant); JSONB → TEXT, array ops in Python; Gmail/page bindings cut | 1,108 |
| `turns.py`, `dispatch.py`, `turn_hooks.py`, `detached.py`, `aio.py` | The loop (`TurnRunner`) and its per-call chain moved out of `engine.py`; the hook points are new; `detached.py` follows the shape of CakeCRM `assistant/turns.py`, cut down for one process (§5) | ~700 |
| `deferred.py` | Chatty `deferred_tools.py`; group key = app slug, threshold 100 | 64 |
| `agents.py` | CakeCRM `assistant/identity.py` prompt builder; agents are rows, not a singleton | 137 |
| `backend/core/memory/facts.py`, `context_files.py`, `tools.py`, `router.py` | `facts.py` from CakeCRM `backend/memory/service.py` (FTS5, temporal facts, soft invalidation); `context_files.py` from CakeCRM `backend/context_files/service.py`, tsvector → FTS5 | 523 |
| `backend/core/memory/observer.py`, `dreaming.py`, `jobs.py` | The observer from Chatty plus CakeCRM `backend/memory/observer.py`; dreaming is new, plain Python with no model call (it merges duplicate facts); nightly and setting-gated | 275 |
| `router.py`; the inbound server `backend/core/mcp/` and the outbound client `backend/core/mcp_servers/` | CakeCRM `assistant/router.py` and `providers/router.py`, minus uploads; todo-gtd `backend/mcp_server.py` HTTP section plus new code; new | 207 / 303 / 557 |

Inbound MCP landed as its own core package, `backend/core/mcp/` (`mcp.md` §1), not `agent/mcp_server.py`. `execute.py` (`run_tool(user, spec, args, *, source)`) is the one path that runs a registry tool and records its tool run: the turn loop's ungated calls, `confirm` (which passes the pending run's id to claim it), and inbound MCP. The turn loop writes two kinds of run itself, with no handler: `core_find_tools` (deferred loading, `done`) and refusals (an unknown or unloaded tool, a call past the write budget; `error`).

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
  requested_at, resolved_at, resolved_by,
  client                       -- the AI tool of an MCP call (mcp.md §1), else NULL
)                              -- the pending store and the audit log
core_agent_facts(text, tags JSON, valid_from, invalid_from, invalidated_by, superseded_by,
                 source_conversation_id, author_user_id, created_at)   -- + FTS
core_agent_observations(conversation_id PK, through_message_id, pending, marked_at, observed_at, facts_added)
  -- the observer's per-conversation ledger
core_agent_context_files(agent_slug, filename COLLATE NOCASE, content, is_protected, updated_at, updated_by)
  -- UNIQUE(agent_slug, filename); agent_slug matches core_agents.slug by value; + FTS
core_agent_providers(provider PK, api_key_enc, model_default, model_light, enabled, updated_at)
core_agent_turns(id, conversation_id, user_id, status, started_at, ended_at)
  -- status CHECK (running | done | error | cancelled | interrupted); one row per turn (§5)
core_agent_turn_events(turn_id, seq, event JSON, PRIMARY KEY (turn_id, seq))
  -- the events a turn streamed, for replay; transport, not the record: pruned 7 days after the turn ends
core_agent_mcp_links           -- mcp.md §1
core_agent_mcp_servers         -- mcp.md §2
```

Memory search is FTS5 only; there is no vector table.

## 3. Memory and privacy (decided)

1. Memory, facts, observations and context files are **install-shared business memory**.
2. Conversations are **private to their user**: a `user_id` filter on every read, including FTS.
3. `observer.py` extracts business facts only, from conversations **not** marked `is_private`, under a prompt that forbids personal details about members.
4. Extracted facts carry provenance: `source_conversation_id` and date. The observer writes them as the system principal (`author_user_id = 0`) tagged `observed`, so the member is traceable only through the conversation id.
5. **An admin sees that provenance metadata and can "delete" the fact; nobody but its user can read the conversation itself.** Deleting a fact ends its validity (`invalid_from`, `invalidated_by`); the row and its text stay, and an admin's history search still finds it.
6. Context files are admin-edited. `is_protected` files (soul, MEMORY) are writable **only through a confirmed chat tool by an admin**, never through MCP or jobs. That tool acts on Whisk's files only (`backend/core/memory/tools.py`), so another agent's protected files cannot be written yet.
7. Unattended runs (`source='job'`) run as the **system principal** (`core_users.id=0`, role `system`, member-level reads only, no private records, cannot authenticate) and may only call tools that are `writes=False`, not `always_confirm`, not remote, and not `untrusted_source`. **Enforced in `registry.for_source`, not by convention.** No job runs tools yet: the nightly job calls the model directly, so the filter is exercised only by tests.

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
    summary: str = "",  # user-facing Approve card line; empty shows only name and args
    title: str = "",    # MCP display title; empty derives one from the name. Not in tool_def_sha256
    destructive: bool = False,  # MCP destructiveHint: the write discards data for good. Not in tool_def_sha256
)
```

`spec.calling_client` is a context variable holding the MCP client's self-reported name while an
inbound MCP call runs (`None` in chat and jobs). A `handler_in` may read it for provenance (Todos
stores it as `source_client`); a `handler` runs in a worker thread and does not see it.

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
5. A write tool has `handler_in` **and** `targets`, or is marked `external_effect`. A tool that only creates a new record, and changes no existing one, returns an empty list (`targets=lambda args: []`). If the new record merely stores a reference to an existing one (a contact on a new deal), its `handler_in` checks read access on it, because the engine authorizes only what `targets` names. If the call also changes an existing record or its links (a new person linked to an organization), that record goes in `targets`, as `core_create_person` does.
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
8. `server_id` and `server_url`: the remote server for remote tools, null for local ones;
9. `summary`, when set.

So a pending approval is bound to exactly what was shown, where it will run, and the implementation revision.

Empty summaries are omitted so tools without a summary keep their existing fingerprint. Changing a summary makes a pending approval stale.

The hash is the sha256 hex of `json.dumps(fields, sort_keys=True)` over the fields above.

### Registry sources and refresh

Sources: core packages' `tools.py` (contacts, notes, reminders, memory and context files, listed below; `apps-and-contracts.md` §9), discovered apps' `get_tools()`, and MCP servers (`mcp.md`). Outbound MCP servers are the one source that changes after boot: `registry.swap_server(server_id, specs)` replaces one server's specs, rebuilds and validates the whole registry, and **swaps it in atomically** (a refused build changes nothing). Old specs stay valid for already-pending approvals only until their `tool_def_sha256` check fails. `build_registry` also refuses a remote spec (`server_url` set) that is not `always_confirm`, `untrusted_source` and `external_effect`.

Deferred tools (`deferred.py`): groups keyed by app slug, deferral threshold 100 tools.

### Core tools

Every install has these, from core packages' `tools.py`. The contacts, note and reminder tools are enabled for any active admin or member (never the system principal), and each result carries the record's `url`. The three directory writes confirm, since they add records every member sees; `core_add_note` and `core_set_reminder` are routine (no Approve card, like `crm_create_deal`): small, the user's own, and reversible.

| Tool | Kind | What it does |
|---|---|---|
| `core_search_contacts` | read | FTS search over people and organizations (`kind` person, organization or any); people come with their organizations and roles. |
| `core_get_person` | read | A person with organizations and roles, channels and one-line addresses; a merged id answers with the survivor plus `merged_from`. |
| `core_get_organization` | read | An organization with its people and roles, channels and addresses. |
| `core_create_person` | write | Creates a person, optionally linked to `organization_id` with `role` (that organization is the target). A live person with the same name returns `{created: false, existing}` unless `allow_duplicate`. |
| `core_create_organization` | write | Creates an organization; a live one with the same name returns `{created: false, existing}`. |
| `core_link_person_organization` | write | Links a person and an organization with a role (`primary` optional); both are targets. |
| `core_add_note` | routine write | A timeline note on any registered record, authored by the user; the record is the target, so it needs write access. An unknown `entity_type` is refused with the registered types listed. |
| `core_set_reminder` | routine write | A reminder on a readable record, owned by the user and titled with the record's name; a `due_at` without an offset is read in the install timezone. No targets (the record does not change). |
| `core_list_my_reminders` | read | The user's reminders, soonest first: `open` (default, snoozed included) or `done`, with `due_local`. |
| `core_memory_search` | read | Facts and Whisk's context files. |
| `core_memory_remember` | write | Records one business fact. |
| `core_context_file_read` | read | One of Whisk's context files. |
| `core_context_file_write` | write | Replaces a context file, protected ones included: admin only, `always_confirm`, not over MCP. |

## 5. Turn loop

CakeCRM's loop, minus Google/Odoo/QuickBooks/todo/meeting logic, plan mode, LLM smart titles, GCS, and Chatty's `/tool/execute`.

1. Compaction at **70%** of the context window, via the light model tier (`compaction.py`).
   - **Template and check.** The gist has fixed sections (Goal, Constraints, Decisions, Done / In progress / Blocked, Pending user asks, Exact identifiers). Code then requires, verbatim and as whole tokens, the latest user message among the compacted rows (its first 300 characters) and up to 12 identifiers (ids, amounts, URLs, dates; `{"…id": n}` in tool args and results), newest rows first, then the previous gist's. The summarizer is told the list up front; a miss gets up to two corrective retries naming what is missing, and a third miss stores nothing (the history stays uncompacted). Non-timeout provider failures also store nothing.
   - **Timeout.** One 90 s deadline covers every attempt. Past it the boundary still advances with no new summary: the gist is the previous one plus a note that older messages were dropped, so the next turn neither waits again nor grows.
   - **Memory flush.** Before summarizing, while the nightly memory pass is on (`agent.nightly_enabled`: it is the observer running early, so it follows the observer's switch), one silent light-tier call offers only `core_memory_remember` over the user rows the nightly observer has not read yet below the boundary, under the observer's rules (§3). Facts go in as the observer writes them (system principal, `source_conversation_id`, tags `observed` and `compaction`, at most 8), and the observer's watermark moves past what the flush read, so each row is flushed or observed once. Private and tainted conversations are skipped, re-checked in the write transaction. The context-file write always confirms, so it is never offered here.
2. Reads run immediately through `handler(user, args)`.
3. A call confirms when the tool is `always_confirm`, or when it is a write that is not routine, is `external_effect`, runs in a tainted conversation, or whose `hides_when(args)` is true or raises. A confirming call inserts a `pending` tool run and emits `confirm`; the client continues by posting `/api/agent/chat` with the conversation id and no message.
4. Results from `untrusted_source` tools are fenced with `delimiters.wrap_untrusted_external` and taint the **conversation** (`core_agent_conversations.tainted`), permanently and across compaction: every later write in it confirms, routine ones included.

The loop is `turns.TurnRunner(state, emit).run()`: it hands each event to `emit` as a dict and ends with exactly one terminal event (`done` or `error`). `dispatch.run_call` settles one tool call (refuse, `core_find_tools`, gate for approval, or run). `engine.py` keeps `chat_tools`, `needs_confirmation` and `confirm`.

### Hook points

`turn_hooks.py` holds everything a hook author needs: `TurnState`, the result types and `register(point, fn)`. A core module registers at import and is imported on the `# hook modules` line of `turns.py`; hooks run in registration order. `register` is the guard registry: an unknown point raises (so a typo stops boot), and a function already registered is not added twice. A hook is `def` or `async def` and runs on the event loop, so a `def` hook must not block; database work goes through `aio.in_thread`. A hook that raises ends the turn with the generic `error` event. The module is not `hooks.py` because a core package's `hooks.py` `HOOKS` is entity-event subscriptions. All five points ship empty. Tests swap a list with `monkeypatch.setitem(turn_hooks.REGISTERED, point, [fn])`.

| Point | Signature | Runs | What the loop does with the answer |
|---|---|---|---|
| `before_model_call` | `(state) -> None` | Before every model call: each iteration, each retry, the approval narration | Nothing; the hook may edit `state.messages` and `state.system` |
| `on_provider_error` | `(state, err: ProviderFailure) -> Retry \| Fallback \| Fail \| None` | When a model call's stream yields an `error` before any of its output reached the client (after output, the turn fails as before) | First non-None answer wins; none is `Fail()`. `Retry(delay)` sleeps (at most 30 s) and calls again; `Fallback(provider)` switches provider for the rest of the turn and rebuilds `state.messages` from the saved conversation, dropping in-memory edits made earlier in the turn; `Fail(message)` ends with `error` (`message`, or the provider's text). The third failure of one call ends the turn whatever a hook says (`MAX_PROVIDER_FAILURES`) |
| `before_tool` | `(state, call) -> str \| None` | Before every tool call is settled (after the write-budget stop). `call` is `{id, name, args}` | First non-None string refuses the call: an `error` run with that text, `tool_end` status `error` |
| `on_tool_result` | `(state, call, run) -> str \| None` | After a call ran through `execute.run_tool`; `run` is its outcome plus `content`, what the model will be shown | Chained: each non-None answer replaces `content`. Only the model's view of this turn changes; `tool_end` and the stored run do not, so a later turn sees the stored result |
| `end_of_turn` | `(state) -> list[dict] \| None` | Once, when the turn ends with `done` (the model stopped, the write budget ended it, or a write waits and the narration succeeded); not on `error` or Stop | Each dict is emitted as an event, in order, just before `done` |

`TurnState` fields are added, never renamed: `user`, `agent`, `provider`, `conversation_id`, `turn_id`, `messages` (provider-native), `system`, `iteration`, `usage` (the last call's), `tainted`, `budget`, `by_name`, `loaded`, `deferred_specs`, `pending`, `terminated`, and `scratch` (a hook's own per-turn storage, keyed by its module name). Hooks change only `messages`, `system` and `scratch`.

### Server-owned turns

`detached.py` owns each turn as an asyncio task, so a client that drops no longer ends it. `start()` creates a supervisor task before its first await; the supervisor saves the user message and the `running` turn row in one transaction, runs the `TurnRunner`, and writes the events. The request only waits for that first transaction, and a request that goes away even then still gets its message answered.

- Every event gets `seq` (0, 1, ...); the first also carries `turn_id`. A live turn keeps its events in memory, and every reader (the POST that started it, `GET /turns/{id}/events?after=N`) tails that list. An ended turn is replayed from `core_agent_turn_events`.
- One writer per turn: events are written in batches every second, and the terminal event is committed in the same transaction as the final status. Readers get the terminal event only after that commit, so a client that re-reads the conversation on `done` never finds its turn still running. If the final write fails three times the stream still ends and the row stays `running` until the next start.
- At most one running turn per conversation: in one process the set of live turns is the truth, so a second POST is 409 `turn_running` and saves nothing.
- Stop (`POST /turns/{id}/cancel`) cancels the runner; the turn ends with `{type: "done", stopped: true}` and status `cancelled`. Shutdown does the same with `{type: "error", interrupted: true}` and status `interrupted`, and the lifespan closes the database only when every turn has ended (`scheduler.md` §4). Neither saves the iteration that was cut off; the iterations before it are already saved.
- A worker thread cannot be stopped: turn-owned database calls go through `aio.in_thread`, which lets the current call finish before a cancel goes on (a tool already running finishes, up to its timeout).
- Startup marks turns left `running` `interrupted`, with a terminal `interrupted` event in their log.

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

Every event also carries `seq`, its position in the turn (from 0), and the first carries `turn_id`. An `end_of_turn` hook may add event types of its own; the client ignores types it does not know.

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
| `confirm` | `{tool_run_id, tool, tool_use_id, msg_id, args, summary}` |
| `done` | `{model}`, or `{stopped: true}` after Stop |
| `error` | `{error}`, plus `interrupted: true` when the server stopped or restarted mid-turn |

## 9. Zero keys

1. `GET /api/agent/status` → `{configured: false}`.
2. `POST /api/agent/chat` returns **400** `{detail: "no_provider"}`.
3. The Whisk page shows the card with an admin link to Settings → AI.
4. The registry and inbound MCP still work.
5. The nightly job `core.agent_nightly` has no up-front key check. It is skipped (`no_provider`) when the observer reaches a model call; otherwise it finishes `ok` and dreaming, which uses no model, still runs. The CRM's `crm.touch_count` LLM work is skipped too.

## 10. Default `soul.md`

`soul.md` is a protected context file of an agent (`core_agent_context_files`, keyed by `agent_slug`), with its default text in `backend/core/memory/context_files.py`. Startup seeds it for Whisk only (`context_files.seed_defaults_in`, default agent `whisk`). It is the only soul: the agent row has no soul column. The default says Whisk is the business assistant for this install; knows the installed apps, the contacts directory and each app's records; answers from them, says what it changed, proposes a write before making it; plain-spoken, brief, careful with anything that leaves the install or hides a record.

## 11. Routes

| Route | Contract |
|---|---|
| `GET /api/agent/status` | `{configured, default_agent, providers, models: {default, light}}`. |
| `POST /api/agent/chat` | The SSE stream of one turn. Body `{conversation_id?, agent_slug?, message?}`; no message plus a `conversation_id` continues after an approval. 422 when both are missing, 404 `conversation_not_found`, 400 `{detail: "no_provider"}` with zero keys, 409 `turn_running` while the conversation has a running turn. The turn is server-owned (§5): it carries on if the client goes. |
| `GET /api/agent/turns/{id}/events?after=N` | SSE: the turn's events with `seq > N` (default -1: all), then live ones until it ends. Only the user who started it; anyone else 404 `turn_not_found`. |
| `POST /api/agent/turns/{id}/cancel` | Stop a running turn: `{cancelled: true}`, or `false` when it had already ended. Owner only (404 otherwise). |
| `POST /api/agent/confirm` | §6. |
| `GET` / `POST /api/agent/conversations`; `GET` / `PATCH {title, is_private}` / `DELETE /api/agent/conversations/{id}` | The caller's own conversations only. |
| `GET /api/agent/agents`; `PATCH /api/agent/agents/{slug}` (admin) | The PATCH takes `name`, `personality`, `provider_override` (`anthropic` or `openai`), `model_override` and `model_tier` (`default` or `light`). |
| `GET /api/agent/providers`, `PUT /api/agent/providers/{provider}`, `POST /api/agent/providers/{provider}/test` (admin) | Provider keys and default and light models, one `core_agent_providers` row per vendor. |
| `GET /api/core/context-files[?agent=<slug>]`, `GET` / `PUT /api/core/context-files/{filename}[?agent=<slug>]` | Context files per agent (default `whisk`). Members list them and read the unprotected ones; admins read all and write through `PUT`. Protected files (`soul.md`, `MEMORY.md`) refuse the REST editor: they change only through the confirmed chat tool. |
| `GET /api/core/memory/facts[?q=&limit=&offset=&history=]`, `POST /api/core/memory/facts {text, tags, valid_from?}`, `DELETE /api/core/memory/facts/{id}` (admin) | Install-shared facts, not per agent. Any signed-in user may list and add; only admins end one. Admins see provenance, and `history=true` (admins only) adds ended facts. `offset` applies only without `q`. `DELETE` ends the fact's validity (§3). |
| MCP links | `GET` / `POST /api/core/mcp/links`, `DELETE /api/core/mcp/links/{id}` (`mcp.md` §1). |
| MCP servers | `/api/core/mcp/servers` (admin; `mcp.md` §2), not under `/api/agent`. |

The routes under `/api/agent` are in `backend/core/agent/router.py`; the memory routes are in `backend/core/memory/router.py`.

## 12. Jobs

`core.agent_nightly` at 02:00 (timeout 1,800 s), gated by the setting `agent.nightly_enabled`: the observer, then dreaming. With zero keys it is skipped only when the observer reaches a model call (§9). `core.agent_turn_events_prune` every 24 h drops the events of turns that ended over 7 days ago (the turn rows stay). See `scheduler.md`.

## 13. FakeProvider

The Step 1 engine stub is gone; the full loop (`turns.py`) runs every turn. `providers/fake.py` is a scripted provider for tests and keyless local runs: `AGENT_FAKE_PROVIDER=1` makes `get_provider` return it and `/api/agent/status` report `configured: true`. With nothing scripted, a user message `/tool <name> <json args>` calls that tool, so a confirmed `handler_in` write can be driven by hand. A scripted `{"chunks": [...], "delay": s}` streams each chunk as its own `text` event `delay` seconds apart, for tests of a turn that outlives its request.

## 14. Frontend (`frontend/src/core/agent/`)

| Piece | Source | What it does |
|---|---|---|
| `WhiskPage` | Chatty `agent/AgentPage.tsx` | `/whisk/*` (one splat route, lazy): conversation list beside the chat; `/whisk/<id>` opens a thread, another user's id answers 404 and shows "not found". |
| `AgentChatPanel` | Chatty `AgentChatPanel.tsx` | Messages, composer (Enter sends, Shift+Enter adds a line, Stop while streaming), context meter from `usage`. |
| `useAgentChat`, `chatModel`, `sse` | Chatty `useAgentChat.ts` | POST /chat read as SSE over `fetch`; an assistant message is ordered text and tool parts, so a reloaded thread (consecutive assistant rows merged) looks like the streamed one. |
| `AgentMessageBubble` | Chatty `AgentMessageBubble.tsx` | Markdown text, collapsible tool calls (args, result, status), compaction note, stream errors. |
| `ToolConfirmCard`, `confirmState` | Chatty card, CakeCRM resolve rule | The Approve card: tool, summary (or nothing), full args. Reloaded threads have no summary because conversation reads do not carry one; collapsed tool calls still use the model-facing description. `pending → sending → resolved`; a failed request returns to pending. Each of `done`, `error`, `uncertain`, `stale`, `denied`, `already_resolved` has its own words. |
| `ConversationSidebar`, `useConversations` | Chatty | Search (`?q=` over message text), new, inline rename, private toggle, delete with confirm. |
| `MarkdownContent` | shared with the Guide (`src/shared/`) | GFM, no highlighting; in-app links stay in the tab through `Link`, external ones open a new tab; images never load. |
| `ZeroKeyCard` | new | `status.configured:false`: replaces the composer; admins get a link to Settings, AI, members are told to ask an admin. Old threads still open. |
| `settingsCards.ts`, section `ai` (admin, order 70) | CakeCRM `ProviderSetup` (Providers), Chatty `AgentContextEditor` (Memory) | Providers (key set/replace/remove via `has_key`, both model tiers, enabled, Test), Agents (name, personality, provider and model override, tier), Memory (context files with protected ones read-only; facts with provenance and "End validity"), Nightly run (`agent.nightly_enabled`). |
| `McpLinksCard` (`src/core/mcp/`), `McpServersCard` (`src/core/mcp_servers/`) | new | Settings → MCP (member-visible: the caller's links; a new link's URL is shown once, with a tab of setup steps per AI client: `clients.ts`) and Settings → MCP servers (admin: add, edit, enable, Refresh, Test, Remove). Each area has its own `settingsCards.ts`; see `mcp.md`. |

Rules the frontend keeps:

1. **Resume after approval.** Once every card of a message has resolved, the client posts `/chat {conversation_id}` with no message, so the model hears every outcome, a deny included. It does not resume when every answer was `already_resolved` (another tab decided).
2. **Reconnection.** The hook keeps the turn's `turn_id` and the last `seq` it applied, and ignores an event it has already seen. A stream that errors or ends without `done`/`error` re-attaches with `GET /turns/{id}/events?after=<seq>`, with backoff (0.5 s doubling to 8 s; progress resets it; while the tab is hidden it waits until the tab is visible). When the tab becomes visible during a turn it re-attaches at once, since a stream can die silently while a phone is locked. A drop it cannot re-attach to (no `turn_id` yet, or the turn is gone) re-reads `GET /conversations/{id}` with the same backoff and shows what was saved, pending cards included. Stop posts `/turns/{id}/cancel` (once the id is known), reads the stream to its stopped `done`, then re-reads the conversation once; if the cancel cannot be sent it aborts the stream instead. A reloaded page does not re-attach to a turn still running; sending then gets the 409 message.
3. A `confirm` event has no `tool_end`; the call's part becomes the card (status `pending`).
4. A 400 `no_provider` from `/chat` re-reads `/status`, which brings up the zero-key card.
5. The shared dialog host is `frontend/src/shared/ConfirmHost.tsx`, lifted from CakeCRM; it is not an agent piece (the Approve card is `ToolConfirmCard`).

## Tests that pin this

- Registry rejects duplicate/unprefixed/tier-on-read specs; `for_source("job")` excludes writes; `for_source("mcp")` excludes protected and remote tools.
- Zero-key status + 400.
- FakeProvider streams text + a write tool → `confirm`, pending run, approve by a non-owner 403, stale `tool_def_sha256` → `stale`, approve executes once with args from the DB (double approve = `already_resolved`), deny recorded, `executing` at startup → `interrupted`.
- No network or LLM call inside `transaction()`.
- `test_agent_turns.py`: a turn survives a disconnect and saves its reply; `after=N` replays each later event once, live and from the log; cancel records `cancelled`; a second running turn is 409; startup and shutdown mark `interrupted`; the prune; a request cancelled while the turn starts still gets an answer; the final log write is retried. `test_agent_hooks.py`: each hook point's contract. `useAgentChat.test.tsx`: resume after a drop and on `visibilitychange`, and Stop.
- `test_scenarios.py` runs `backend/tests/scenarios/*.yaml` (format in `testing.md`, "Whisk scenarios"): fencing and taint, approve then continue, compaction keeping identifiers, a lossy summary retried then rejected, a dropped turn resuming. `test_agent_compaction.py`: identifier extraction and matching, retries, the timeout fallback, the flush and its privacy checks. `test_prompt_budget.py`: the static prompt plus eager tools stay under a token budget.
- Playwright: Whisk answers with FakeProvider → write tool shows Approve and runs on approve → zero-key card.

## Source

Build plan: §5 (all), §2 (system principal), §6 (exclusions, remote specs), §11 (the nightly agent job), Decisions (Agent), Step 1, Step 2 W9, Step 3 W12, Step 4 W14–W16, Risks 5 and 8, Verification.
