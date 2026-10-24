# MCP: inbound links and outbound servers

**What this covers:** §6. Inbound: a per-user MCP link that is an API key for that user, immediate writes, exclusions, the HTTP rules lifted from todo-gtd, the SDK choice, URL forms. Outbound: the servers table, discovery and refresh, naming, every call confirms, untrusted fencing, the address policy enforced at connection time, and the DNS-rebinding test.
**Who reads it:** W14 (MCP server), W15 (MCP client), W9/W12 (registry and confirmation), the MCP settings cards.

Code: the inbound server is the core package `backend/core/mcp/`, and the outbound client is `backend/core/mcp_servers/`; both land with the MCP workstream. Both work with zero AI keys.

## 1. Inbound (`backend/core/mcp/`)

### Table

```sql
core_agent_mcp_links(user_id, token_hash UNIQUE, label, created_at, last_used_at, revoked_at)
```

The token is shown **once** at creation; only its hash is stored.

### A link is an API key for its user (decided)

1. `call_tool` **executes immediately**, as the link's user.
2. Every call is logged in `core_agent_tool_runs` with `source='mcp'`.
3. The MCP client's own approval UI is the user's gate.
4. The link can be revoked at any time (`revoked_at`).
5. Deactivating a user revokes their links.
6. The system principal can never mint a link.

### Exposed tools

```
exposed = registry.for_user(link.user) ∩ registry.for_source("mcp")
```

1. Never protected context-file writes (soul, MEMORY).
2. Never remote (outbound) tools.
3. Admin-only tools are filtered by role.
4. `list_tools` returns JSON-schema `Tool`s with `readOnlyHint = not writes`.

### HTTP rules (lifted from todo-gtd `backend/mcp_server.py` HTTP section and `backend/ratelimit.py`)

| Request | Response |
|---|---|
| Path token `/mcp/<token>` that is unknown, revoked or deactivated | **404**, never 401. |
| Bearer `/mcp` with a bad or missing token | **401**. |
| `/.well-known/…`, `/register`, `/authorize`, `/token` | **404** (no OAuth; a client finds no sign-in and uses the link as is). |
| Body over **4 MB** | Refused (413 in the donor). |
| More than **600 calls/min per link**, or over the per-IP limit (the donor's `IPRateLimiter(window=60, max_hits=600)`, lifted) | Refused by the rate limiters. Both apply. |
| A request carrying an `Origin` header | Refused. |

The plan cites the donor section as lines ~700–946; at the recorded donor sha it is lines 832–946 (`source-map.md`).

Open (pinned by the implementing workstream, which updates this doc): whether a link use updates `last_used_at` on every call. The token format and length. Link mint/list/revoke routes (shape to be pinned by W14).

### SDK

Use the `mcp` SDK's **low-level `Server`** with `StreamableHTTPSessionManager(stateless=True, json_response=True)`. (The todo-gtd donor uses FastMCP; only its HTTP section is lifted.)

### URL forms

| Client | URL |
|---|---|
| claude.ai custom connector, Claude Desktop | `https://host/mcp/<token>` |
| Claude Code | `https://host/mcp` + `Authorization: Bearer <token>` |

The MCP bearer is the link token, not the session JWT. The cookie CSRF rules (`auth.md` §3) cover cookie-authenticated `/api` requests; `/mcp` sits outside `/api` and authenticates by link token.

## 2. Outbound (`backend/core/mcp_servers/`)

Code: `client.py` (discovery, remote specs, calls), `transport.py` (the address policy), `service.py` (the table), `router.py`, `jobs.py`, `startup.py`. Frontend: `frontend/src/core/mcp_servers/` (Settings → MCP servers).

### Table

```sql
core_agent_mcp_servers(id, name, url, token_enc, prefix UNIQUE, enabled, tools_json, last_discovered_at, last_error, created_at, updated_at)
```

`token_enc` is encrypted with the install key (`enc:v1:`, `''` = no token) and sent as `Authorization: Bearer <token>`. `tools_json` is what the registry holds for the server now (`[{name, description, read_only_hint}]`, `[]` when disabled or failing). `last_discovered_at` is the last successful discovery; `last_error` the last failure (cleared by a success).

### Discovery and refresh

1. Client: `mcp` SDK `streamable_http_client` + `ClientSession`, one short session per exchange, driven from sync code with `anyio.run` in a worker thread.
2. Discovery runs at startup (`startup.py`, in a background thread, so boot never waits on the network), on create, update and "Refresh" (admin), and hourly through the job **`core.mcp_discover`** (scheduler, `every=3600`, servers one after another).
3. Each server's tools are swapped into the registry **atomically** with `agent.registry.swap_server(server_id, specs)`: the whole registry is rebuilt and validated, then replaced. Old specs stay valid for already-pending approvals only until their `tool_def_sha256` check fails.
4. A failing server drops its tools (and records `last_error`), not the app. Disabling a server drops its tools; deleting it too.
5. A tool whose wire name would not match `^[a-zA-Z0-9_-]{1,64}$` or whose schema is not `type: object` is skipped (logged). At most 200 tools per server; descriptions are cut at 1,000 characters.

### Naming

| Where | Form |
|---|---|
| Wire name (sent to providers) | `<prefix>__<tool>`, e.g. `todogtd__todo_create` (provider APIs forbid `.`). |
| Display name | `<prefix>.<tool>`, e.g. `todogtd.todo_create`. The spec's description starts with it: `todogtd.todo_create, a remote tool on <server name>: …`, so the Approve card shows it. |
| Prefix | `^[a-z][a-z0-9_]{1,19}$`, unique, not a reserved slug or an installed app's slug. The spec's `app` is the prefix (deferred-tool grouping). |

### Every remote call confirms

1. Remote specs have `always_confirm=True`, `untrusted_source=True`, `external_effect=True`, `mcp_exposed=False`, `handler` (never `handler_in`). `build_registry` refuses a remote spec (`server_url` set) without the first three.
2. Remote annotations are **untrusted metadata**: `readOnlyHint` sets `writes` (for display and the write budget) but never skips confirmation.
3. Results are fenced by the engine with `delimiters.wrap_untrusted_external` and taint the whole conversation, so every later write in it confirms (`agent.md` §5). A result is the text blocks (or the structured content when there is no text); a server-flagged error comes back as `{"error": …}`.
4. Remote tools are external-effect: claimed in one transaction, executed outside, resolved in another; any failure, a timeout included, marks `uncertain` (`agent.md` §6).
5. `tool_def_sha256` for a remote tool includes the server id **and URL**.
6. Remote tools are never exposed inbound and never run from jobs.
7. The handler re-reads the server row at call time and refuses if it was disabled, deleted or moved to another URL since the spec was built.
8. Remote tools are offered to every signed-in user's Whisk (the server and its token are install-wide); each user approves their own calls. The settings card says so.
9. The Approve card shows the full args.

### Address policy (enforced at connection time)

1. Destinations: **https only**.
2. **Refused:** loopback, private-network, link-local, and IPv4-mapped IPv6 addresses; in code, any address that is not `is_global`, is multicast or is IPv4-mapped. IP literals in the URL go through the same check.
3. `MCP_ALLOW_PRIVATE=1` permits those addresses and also permits `http://`, but `http://` only to them (never to a public address).
4. Enforced **at connection time**, not by a one-off hostname check. A custom `httpx2` transport (the SDK's HTTP client) whose httpcore network backend:
   1. resolves the host on every new connection;
   2. validates **every** returned address before connecting to any;
   3. connects to a validated IP; httpcore then starts TLS with the URL's hostname, so SNI and certificate verification are unchanged;
   4. does **not** follow redirects (`max_redirects=0`, which also stops the SDK's own same-origin following).
5. 30 s timeout (per request and for the whole exchange); response capped at **1 MB** (counted on the wire); compressed responses are refused (`Accept-Encoding: identity`), so the cap holds after decoding. No proxies or netrc from the environment.
6. HTTP 401/403 surfaces as "The server refused the token"; the SDK would only say "an error response".
7. The transport refuses to send inside a database transaction.

### Routes (admin, `/api/core/mcp/servers`)

| Route | Contract |
|---|---|
| `GET /` | `[S]`. |
| `POST /` `{name, url, token?, prefix}` | Creates, discovers, returns `S`. 422 on a bad prefix or URL (http only with `MCP_ALLOW_PRIVATE=1`), 409 `prefix_taken`. |
| `PATCH /{id}` `{name?, url?, token?, prefix?, enabled?}` | `token: ""` clears it; null or omitted leaves a field. Rediscovers; returns `S`. |
| `DELETE /{id}` | 204; the server's tools leave the registry. |
| `POST /{id}/refresh` | Rediscovers; returns `S` (tools or `last_error`). |
| `POST /{id}/test` | `{ok, tools: n, error?}`; changes nothing. |

`S = {id, name, url, prefix, enabled, has_token, tools: [{name, description, read_only_hint}], last_discovered_at, last_error, created_at, updated_at}`. The token is never returned.

### First target

todogtd.com is the first outbound server the plan names.

## Tests that pin this

- MCP link lists role-filtered tools and executes an attributed write via a real `ClientSession` over `httpx.ASGITransport`.
- Revoked and deactivated links 404.
- Origin refused.
- `for_source("mcp")` excludes protected and remote tools.
- Outbound (`test_mcp_servers.py`, against a local `MCPServer` stub over loopback with `MCP_ALLOW_PRIVATE=1`): discovery and prefixing, the hash covers the URL (a URL change makes a pending approval stale), a remote read still confirms through the engine and runs once on approve, the result is fenced and taints the conversation, a failing server drops its tools and sets `last_error`, disabling drops tools, private/loopback/link-local/IPv4-mapped destinations refused, `http://` only with `MCP_ALLOW_PRIVATE=1`, 1 MB cap, no send inside a transaction.
- DNS rebinding: a stub resolver returns a public address first and a private one second; the second connection is refused and nothing connects to the private address. A mixed answer (public + private) is refused before any connection.

## Source

Build plan: §6 (all), §5 (`ToolSpec`, `for_source`, `tool_def_sha256`, confirmation), §1 (encryption), §2 (deactivation, system principal), Decisions (MCP), Risks 8, Verification.
