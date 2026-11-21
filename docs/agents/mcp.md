# MCP: inbound links and outbound servers

**What this covers:** §6. Inbound: a per-user MCP link that is an API key for that user, immediate writes, exclusions, the HTTP rules lifted from todo-gtd, the SDK choice, URL forms. Outbound: the servers table, discovery and refresh, naming, every call confirms, untrusted fencing, the address policy enforced at connection time, and the DNS-rebinding test.
**Who reads it:** W14 (MCP server), W15 (MCP client), W9/W12 (registry and confirmation), the MCP settings cards.

Code: both halves are built. The inbound server is the core package `backend/core/mcp/` (`links.py` for the links, `router.py` for the link routes and the `/mcp/{token}` and bearer `/mcp` endpoints, `server.py`, `startup.py`), with `backend/core/ratelimit.py` for the limits, running tools through `backend/core/agent/execute.py`. The outbound client is the core package `backend/core/mcp_servers/`: servers CRUD, the discovery job `core.mcp_discover`, the address policy, `<prefix>__<tool>` names, fenced results, and servers shared by the whole install (§2). Links, the endpoint and discovery work with zero AI keys; only Whisk's calls to remote tools wait for one. Settings: **MCP** (`mcp`, order 25, member-visible) holds the links card, and **MCP servers** (`mcp_servers`, order 80, admin-only) the servers card.

## 1. Inbound (`backend/core/mcp/`)

### Table

```sql
core_agent_mcp_links(id, user_id, token_hash UNIQUE, label, created_at, last_used_at, revoked_at)
```

Migration `20261020000520_core_mcp_links.sql`. The token is `secrets.token_urlsafe(32)` (256 bits, 43 URL-safe characters), returned **once** at minting; only its sha256 is stored. `last_used_at` is written at most once a minute per link.

### A link is an API key for its user (decided)

1. `call_tool` **executes immediately**, as the link's user, through `execute.run_tool(user, spec, args, source="mcp")`: the same path the chat loop and the approval step use, so targets are authorized for write and a local write runs in one transaction.
2. Every call is logged in `core_agent_tool_runs` with `source='mcp'`, the link's `user_id`, no conversation, and `client`: the calling AI tool's name (below).
3. The MCP client's own approval UI is the user's gate.
4. The link can be revoked at any time (`revoked_at`).
5. Deactivating a user revokes their links (`links.revoke_all_in` on `auth.service.ON_DEACTIVATE`); reactivating does not bring them back. A link whose user is inactive is refused even before that.
6. The system principal can never mint a link, and neither can an inactive account (checked against the live row).

### Link routes (session)

| Route | Contract |
|---|---|
| `GET /api/core/mcp/links` | The caller's live links: `[{id, label, created_at, last_used_at}]`. |
| `GET /api/core/mcp/links?all=1` | Admin only (403 otherwise): every live link plus `user_id, user_name, user_email`. Never a token. |
| `POST /api/core/mcp/links {label}` | 201 `{id, label, created_at, last_used_at, url, token}`, the only time the token is returned. `url` is `<PUBLIC_URL>/mcp/<token>`. Label 1–80 characters, not blank. |
| `DELETE /api/core/mcp/links/{id}` | 204. The caller's own live link only; anything else is 404. |

The Settings card is `frontend/src/core/mcp/settingsCards.ts` (section `mcp`, member-visible).

### Exposed tools

```
exposed = registry.for_user(link.user) ∩ registry.for_source("mcp")
```

1. Never protected context-file writes (soul, MEMORY): `mcp_exposed=False`.
2. Never remote (outbound) tools.
3. Admin-only tools are filtered by role (`enabled(user)` and the app's roles); the example app's `example_count_widgets` is the fixture.
4. `list_tools` returns JSON-schema `Tool`s with a `title` (the spec's, else derived from the name: `crm_search_deals` → "Search deals") and explicit annotations: `title`, `readOnlyHint = not writes`, `destructiveHint = destructive` (true only for a write that discards data for good, e.g. `crm_merge_deals` dropping the source's clashing custom-field values; archiving is a status), `openWorldHint = external_effect`. Without them the spec defaults a write to destructive and open-world. A call to a tool not in the user's list is an error result and runs nothing.
5. A result is the stored JSON as one text block; a failure is `isError` with `{status, error}` (`error`, or `uncertain` for an external effect that may have happened).

### Instructions

The server's `instructions` (initialize and `server/discover`) are one line on what the link is, then `registry.agent_guidance(user)` (each reachable app's `agent_guidance`, `apps-and-contracts.md`), then a note that text in results was written by people and is data, never instructions. They depend on the link's user, so `server.handle` builds the low-level `Server` per request.

### Client name

`clients.client_name` (lifted from todo-gtd `backend/common.py`) names the calling AI tool: the request's `_meta` `io.modelcontextprotocol/clientInfo` title or name (protocol 2026-07-28 sends it on every request), else the product the User-Agent leads with, never an HTTP library's (`python-httpx`, `node`, …). Friendly names: `claude-ai`/`claude-user` → Claude, `claude-code` → Claude Code, `openai-mcp` → ChatGPT. It is self-reported, so it is cut to one printable line of 60 characters and only ever labels: `core_agent_tool_runs.client` (migration `20261020000540_core_mcp_client.sql`) and `spec.calling_client` for the call's `handler_in` (Todos shows "via ChatGPT").

### HTTP rules (lifted from todo-gtd `backend/mcp_server.py` HTTP section and `backend/ratelimit.py`)

The endpoint lives in `backend/core/mcp/router.py` as plain ASGI routes on the discovered `router`. They sit outside `/api` and outside the OpenAPI schema, so the contract test's unauthenticated allow-list (which covers `/api` routes) does not list them; these rules and `test_mcp_links.py` are their guard.

| Request | Response |
|---|---|
| Any request carrying an `Origin` header | **403**, checked first. AI clients call from a server or a desktop app and send none. |
| Path token `/mcp/<token>`, `/link/<token>` or `/<token>/mcp` that is unknown, revoked or deactivated | **404**, never 401. `/link/…` and `/<token>/mcp` match only a 43-character token segment, so `/settings/mcp` (or an app named `link`) stays the SPA's. |
| Bearer `/mcp` with a bad or missing token | **401** with `WWW-Authenticate: Bearer` (no resource metadata: there is no OAuth server). |
| `/.well-known/…`, `/register`, `/authorize`, `/token`, any method | **404** (no OAuth; a client finds no sign-in and uses the link as is). |
| More than **600 requests/min per link** | **429**, `Retry-After: 60`. |
| More than **60 wrong tokens per 10 min from one address** | **429**, `Retry-After: 600`. Only misses are charged and a valid link is always served, so one bad client behind a shared address cannot lock others out. A request with no token at all is not a miss. |
| Declared body over **4 MB** | **413**; the SDK caps a body sent without a length at the same size. |
| GET or HEAD on a live path link without `text/event-stream` in `Accept` (someone opened it in a browser) | **200**, a static guide page (no name, workspace or token on it), `Cache-Control: no-store`, `Referrer-Policy: no-referrer`. The transport would answer 406. |
| Anything else with a live link (POST, and GET/DELETE as the transport answers them) | Handed to the SDK as the link's user. |

Doc drift fixed here: an earlier version gave the per-IP limit as `IPRateLimiter(window=60, max_hits=600)`; in the donor that is the per-link call limit, and the per-address limit is the wrong-token one (`window=600, max_hits=60`).

The logs show `/mcp/***`, `/link/***` or `/***/mcp` instead of the token (`backend/core/logscrub.py`).

The plan cites the donor section as lines ~700–946; at the recorded donor sha it is lines 832–946 (`source-map.md`).

### SDK

The `mcp` SDK (pinned `mcp==2.3.0`, the version todo-gtd's FastMCP resolves) **low-level `Server`** with `StreamableHTTPSessionManager(stateless=True, json_response=True)`. A fresh manager serves each request (`server.handle`), so nothing starts from the app lifespan; the router sets the link's user in a context variable first. (The todo-gtd donor uses FastMCP; only its HTTP section is lifted.) The SDK's client speaks `httpx2`, so the tests drive it through `httpx2.ASGITransport`.

### URL forms

| Client | URL |
|---|---|
| claude.ai custom connector, Claude Desktop | `https://host/mcp/<token>` (the minted shape; `/link/<token>` and `/<token>/mcp` work too) |
| Claude Code | `claude mcp add --transport http springform https://host/mcp/<token>`, or `https://host/mcp` + `Authorization: Bearer <token>` |
| ChatGPT, Gemini | A custom connector (ChatGPT: chatgpt.com/plugins → "Add custom MCP server", "No authentication", then install the plugin) with the link as its URL |
| Cursor, VS Code | A one-click install link, or the `mcpServers` / `code --add-mcp` snippet |
| Codex, Gemini CLI | `codex mcp add springform --url <link>`, `gemini mcp add --transport http springform <link>` |

The Settings card shows a new link once, with a tab per client (`frontend/src/core/mcp/clients.ts`, lifted from todo-gtd) holding its steps or command with the link filled in.

The MCP bearer is the link token, not the session JWT. The cookie CSRF rules (`auth.md` §3) cover cookie-authenticated `/api` requests; `/mcp` sits outside `/api` and authenticates by link token.

## 2. Outbound (`backend/core/mcp_servers/`)

Code: `client.py` (discovery, remote specs, calls), `transport.py` (the address policy), `service.py` (the table), `router.py`, `jobs.py`. Frontend: `frontend/src/core/mcp_servers/` (Settings → MCP servers).

### Table

```sql
core_agent_mcp_servers(id, name, url, token_enc, prefix UNIQUE, enabled, tools_json, last_discovered_at, last_error, created_at, updated_at, trusted)
```

`trusted` (migration `20261020000990_core_gtd_connect.sql`, default 0) is set only by the GTD suite connect (below).

`token_enc` is encrypted with the install key (`enc:v1:`, `''` = no token) and sent as `Authorization: Bearer <token>`. `tools_json` is what the registry holds for the server now (`[{name, description, read_only_hint}]`, `[]` when disabled or failing). `last_discovered_at` is the last successful discovery; `last_error` the last failure (cleared by a success).

### Discovery and refresh

1. Client: `mcp` SDK `streamable_http_client` + `ClientSession`, one short session per exchange, driven from sync code with `anyio.run` in a worker thread.
2. Discovery runs at every boot and hourly through the job **`core.mcp_discover`** (scheduler, `every=3600, on_boot=True`, servers one after another; boot never waits on the network, and shutdown cancels the pass and waits up to 10 s for it), and on create, update and "Refresh" (admin).
3. Each server's tools are swapped into the registry **atomically** with `agent.registry.swap_server(server_id, specs)`: the whole registry is rebuilt and validated, then replaced. Old specs stay valid for already-pending approvals only until their `tool_def_sha256` check fails.
4. A failing server drops its tools (and records `last_error`), not the app. Disabling a server drops its tools; deleting it too.
5. A tool whose wire name would not match `^[a-zA-Z0-9_-]{1,64}$` or whose schema is not `type: object` is skipped (logged). At most 200 tools per server; descriptions are cut at 1,000 characters.

### Naming

| Where | Form |
|---|---|
| Wire name (sent to providers) | `<prefix>__<tool>`, e.g. `todogtd__todo_create` (provider APIs forbid `.`). |
| Display name | `<prefix>.<tool>`, e.g. `todogtd.todo_create`. The spec's description starts with it: `todogtd.todo_create, a remote tool on <server name>: …`, for the model. The Approve card shows the summary `Run <prefix>.<tool> on <server name>.` (never the server's own description) and the full args. |
| Prefix | `^[a-z][a-z0-9_]{1,19}$`, unique, not a reserved slug or an installed app's slug. The spec's `app` is the prefix (deferred-tool grouping). |

### Every remote call confirms (except a trusted server's reads)

1. Remote specs have `always_confirm=True`, `untrusted_source=True`, `external_effect=True`, `mcp_exposed=False`, `handler` (never `handler_in`). `build_registry` refuses a remote spec (`server_url` set) without the first three, except that a trusted server's read (`trusted=True`, `writes=False`) may leave `always_confirm` off.
2. Remote annotations are **untrusted metadata**: `readOnlyHint` sets `writes` (for display and the write budget) but never skips confirmation, unless the server is trusted (below).
3. Results are fenced by the engine with `delimiters.wrap_untrusted_external` and taint the whole conversation, so every later write in it confirms (`agent.md` §5). A result is the text blocks (or the structured content when there is no text); a server-flagged error comes back as `{"error": …}`.
4. Remote tools are external-effect: claimed in one transaction, executed outside, resolved in another; any failure, a timeout included, marks `uncertain` (`agent.md` §6).
5. `tool_def_sha256` for a remote tool includes the server id **and URL**.
6. Remote tools are never exposed inbound and never run from jobs.
7. The handler re-reads the server row at call time and refuses if it was disabled, deleted or moved to another URL since the spec was built.
8. Remote tools are offered to every signed-in user's Whisk (the server and its token are install-wide); each user approves their own calls. The settings card says so.
9. The Approve card shows the full args.

### Trusted servers

A server row with `trusted = 1` is one an admin connected through Settings, GTD suite: the install's own account. Its tools carry `ToolSpec.trusted` (not hashed: a row's trust never changes, and a read's `always_confirm`, which is hashed, already differs).

1. A tool it marks `readOnlyHint` gets `always_confirm=False`, and `engine.needs_confirmation` has one condition for it: a trusted server's read never asks, **even in a tainted conversation**. The tainted-read rule exists because a read's arguments could carry conversation data to a page's author; a trusted read's arguments reach only the account an admin connected.
2. Everything else stays: the result is fenced and taints the conversation (so every later local write, web read and remote write asks), it is `external_effect` (runs in order, never in the parallel lookup batch; a failure is `uncertain`), it is never exposed inbound or to jobs, and saved always-allow rules never cover remote tools.
3. Every other tool on the server is a write and always asks.
4. The hand-add API (`POST`/`PATCH /api/core/mcp/servers`) cannot set `trusted` (both models forbid extra keys), and a trusted server's `url` and `prefix` cannot be changed (409 `trusted_server_fixed`: trust was given to that address under that prefix; disconnect and connect again). Enable, disable, rename and remove work as for any server; removing it also removes its launcher tiles.
5. The MCP servers card shows a **Trusted** chip.

### GTD suite connect (`backend/core/gtd/`)

Settings, **GTD suite** (`gtd-suite`, order 85, admin-only; `frontend/src/core/gtd/`) links the install to a GTD suite account with the suite's device flow. The suite's address is the setting `mcp.gtd_base_url` (default `https://todogtd.com`, scheme and host only), edited on the card.

| Route (admin) | Does |
|---|---|
| `GET /api/core/gtd` | The state. |
| `POST /api/core/gtd/connect` | `GET {base}/api/config` (the tiles; an answer without an `apps` mapping is refused before a code is spent), then `POST {base}/api/connect {"client":"springform"}`. A connect already waiting is returned as is. 429 from the suite → 502 naming the wait. |
| `POST /api/core/gtd/connect/poll` | One `POST {base}/api/connect/poll {device_token}`, no sooner than the suite's `interval` (a 429 waits its `Retry-After`). `pending` → the state; 404 → 409 `gtd_connect_expired`; `approved` → the `agent_url` is checked by the hand-added server rules (`ServerIn`) and stored, with the tiles, in one transaction: a server named "GTD suite", prefix `gtd`, `trusted = 1`, then discovery. |
| `DELETE /api/core/gtd` | Deletes the trusted `gtd` server (tiles go by foreign key, tools leave the registry), or cancels a waiting connect. |

Every route answers `GtdState = {base_url, server: S | null, pending: {user_code, url, interval, expires_in} | null}`; the device token never leaves the server. Every request to the suite goes through `transport.http_client()` (the address policy above, no redirects, 30 s, 1 MB) via `client.run`, never inside a transaction. The card opens `url` in a new tab and asks the server to poll every `interval` seconds.

1. The waiting connect lives in process memory (one process is a platform rule); a restart means clicking Connect again. An approved link, which the suite hands out exactly once, stays there until it is stored: if a hand-added server holds `gtd` meanwhile, each poll answers 409 `prefix_taken` until it is removed, then stores it.
2. Start answers 409 `gtd_already_connected` when connected, `gtd_prefix_taken` when a hand-added server holds `gtd`, 422 when `mcp.gtd_base_url` or the prefix breaks the hand-added server rules (`http://` without `MCP_ALLOW_PRIVATE=1`, or a fork with an app named `gtd`). `gtd` is deliberately not a reserved slug: reserving it would stop an existing fork with a `gtd` app from booting. A `gtd` app installed after connecting clashes only if it defines a tool named exactly like a remote one (`gtd__<tool>`); the registry then refuses that server's tools and records `last_error`, and nothing else breaks. The settings section id is `gtd-suite`, which no app slug can be.
3. Tiles: one per app among `todo`, `notes`, `projects`, `sites`, `brain` that the suite's `/api/config` lists (`apps.{key}.url`, http or https only), titled Todo, Notes, Projects, Sites and Brain, in that order, in `core_launcher_links` with the server's id (`frontend-shell.md`). The hosted suite lists all five; a self-hosted one only the apps it runs.
4. The agent link is stored like any server URL (the token is in its path), shown to admins in the MCP servers card.
5. The connection is install-wide, like every outbound server: the tools reach every member's Whisk with the connected account.

### Address policy (enforced at connection time)

1. Destinations: **https only**.
2. **Refused:** loopback, private-network, link-local, multicast, and IPv6 addresses that carry an IPv4 address (IPv4-mapped `::ffff:0:0/96`, IPv4-compatible `::/96`, NAT64 `64:ff9b::/96` and `64:ff9b:1::/48`, 6to4 `2002::/16`, refused whole rather than decoded); in code, `transport.internal()`. IP literals in the URL go through the same check.
3. `MCP_ALLOW_PRIVATE=1` permits those addresses and also permits `http://`, but `http://` only to them (never to a public address).
4. Enforced **at connection time**, not by a one-off hostname check. A custom `httpx2` transport (the SDK's HTTP client) whose httpcore network backend:
   1. resolves the host on every new connection;
   2. validates **every** returned address before connecting to any;
   3. connects to a validated IP; httpcore then starts TLS with the URL's hostname, so SNI and certificate verification are unchanged;
   4. does **not** follow redirects (`max_redirects=0`, which also stops the SDK's own same-origin following).
5. 30 s timeout (per request and for the whole exchange); response capped at **1 MB** (counted on the wire); compressed responses are refused (`Accept-Encoding: identity`), so the cap holds after decoding. No proxies or netrc from the environment.
6. HTTP 401/403 surfaces as "The server refused the request (HTTP 401); check the token"; the SDK would only say "an error response".
7. The transport refuses to send inside a database transaction.
8. **Web mode** (`http_client(web=True)`, used only by Whisk's `core_web_fetch`, `agent.md` §4): `http://` and `https://` to public addresses only (`MCP_ALLOW_PRIVATE` does not apply); still no automatic redirects: the reader follows up to 5 itself, each hop a new request through the transport (scheme and every address checked, the connection pinned again) whose body is never read, because httpx's own following reads every redirect body in full, decompressed and uncapped; 6 MB raw cap (the reader stops at 5 MB decoded); compressed bodies accepted (httpx2 inflates them in bounded pieces); 401/403 returned as statuses. MCP keeps every rule above.

### Routes (admin, `/api/core/mcp/servers`)

| Route | Contract |
|---|---|
| `GET /` | `[S]`. |
| `POST /` `{name, url, token?, prefix}` | Creates, discovers, returns `S`. 422 on a bad prefix or URL (http only with `MCP_ALLOW_PRIVATE=1`), 409 `prefix_taken`. |
| `PATCH /{id}` `{name?, url?, token?, prefix?, enabled?}` | `token: ""` clears it; null or omitted leaves a field. Rediscovers; returns `S`. |
| `DELETE /{id}` | 204; the server's tools leave the registry. |
| `POST /{id}/refresh` | Rediscovers; returns `S` (tools or `last_error`). |
| `POST /{id}/test` | `{ok, tools: n, error?}`; changes nothing. |

`S = {id, name, url, prefix, enabled, trusted, has_token, tools: [{name, description, read_only_hint}], last_discovered_at, last_error, created_at, updated_at}`. The token is never returned.

### First target

todogtd.com is the first outbound server the plan names.

## Tests that pin this

- MCP link lists role-filtered tools and executes an attributed write via a real `ClientSession` over `httpx2.ASGITransport` (`test_mcp_links.py`).
- Revoked and deactivated links 404; bearer 401; Origin 403; no OAuth discovery; rate limits and the body cap; a system-principal mint refused.
- `for_source("mcp")` excludes protected and remote tools.
- Outbound (`test_mcp_servers.py`, against a local `MCPServer` stub over loopback with `MCP_ALLOW_PRIVATE=1`): discovery and prefixing, the hash covers the URL (a URL change makes a pending approval stale), a remote read still confirms through the engine and runs once on approve, the result is fenced and taints the conversation, a failing server drops its tools and sets `last_error`, disabling drops tools, private/loopback/link-local/IPv4-mapped destinations refused, `http://` only with `MCP_ALLOW_PRIVATE=1`, 1 MB cap, no send inside a transaction.
- GTD suite connect (`test_gtd_connect.py`, against `fixtures/gtd_stub.py`: the device flow, `/api/config` and the MCP stub as `/link/<token>`): connect stores a trusted server and the tiles, a read runs without a card in a clean and in a tainted conversation and taints it, a write asks, disconnect (or removing the server) leaves no server, tiles or tools, the interval and both 429s are honoured, a wrong address spends no code, an approved link survives a prefix clash, a trusted server's address and prefix are fixed. Scenario `trusted_server_read_runs_write_asks.yaml`.
- DNS rebinding: a stub resolver returns a public address first and a private one second; the second connection is refused and nothing connects to the private address. A mixed answer (public + private) is refused before any connection.

## Source

Build plan: §6 (all), §5 (`ToolSpec`, `for_source`, `tool_def_sha256`, confirmation), §1 (encryption), §2 (deactivation, system principal), Decisions (MCP), Risks 8, Verification.
