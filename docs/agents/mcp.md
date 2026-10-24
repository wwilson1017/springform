# MCP: inbound links and outbound servers

**What this covers:** §6. Inbound: a per-user MCP link that is an API key for that user, immediate writes, exclusions, the HTTP rules lifted from todo-gtd, the SDK choice, URL forms. Outbound: the servers table, discovery and refresh, naming, every call confirms, untrusted fencing, the address policy enforced at connection time, and the DNS-rebinding test.
**Who reads it:** W14 (MCP server), W15 (MCP client), W9/W12 (registry and confirmation), the MCP settings cards.

Code: `backend/core/agent/mcp_server.py`, `backend/core/agent/mcp_client.py`. Both work with zero AI keys.

## 1. Inbound (`mcp_server.py`)

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

Open: whether a link use updates `last_used_at` on every call. Open: the token format and length. Open: link mint/list/revoke routes (shape to be pinned by W14).

### SDK

Use the `mcp` SDK's **low-level `Server`** with `StreamableHTTPSessionManager(stateless=True, json_response=True)`. (The todo-gtd donor uses FastMCP; only its HTTP section is lifted.)

### URL forms

| Client | URL |
|---|---|
| claude.ai custom connector, Claude Desktop | `https://host/mcp/<token>` |
| Claude Code | `https://host/mcp` + `Authorization: Bearer <token>` |

The MCP bearer is the link token, not the session JWT. The cookie CSRF rules (`auth.md` §3) cover cookie-authenticated `/api` requests; `/mcp` sits outside `/api` and authenticates by link token.

## 2. Outbound (`mcp_client.py`)

### Table

```sql
core_agent_mcp_servers(id, name, url, token_enc, prefix UNIQUE, enabled, tools_json, last_discovered_at, last_error)
```

`token_enc` is encrypted with the install key (`enc:v1:`).

### Discovery and refresh

1. Client: `mcp` SDK `streamable_http_client` + `ClientSession`.
2. Discovery runs at startup, on "Refresh" (admin), and hourly.
3. Discovered tools are swapped into the registry **atomically**. Old specs stay valid for already-pending approvals only until their `tool_def_sha256` check fails.
4. A failing server drops its tools (and records `last_error`), not the app.

Open: the hourly discovery job is not in §11's core job list; its job name and whether it runs through the scheduler are not stated.

### Naming

| Where | Form |
|---|---|
| Wire name (sent to providers) | `<prefix>__<tool>`, e.g. `todogtd__todo_create` (provider APIs forbid `.`). |
| Display name | `<prefix>.<tool>`, e.g. `todogtd.todo_create`. |

### Every remote call confirms

1. Remote specs have `always_confirm=True`.
2. Remote annotations are **untrusted metadata**: `readOnlyHint` is recorded for display but never trusted to skip confirmation.
3. Remote specs have `untrusted_source=True`: results are fenced with `delimiters.wrap_untrusted_external` and taint the turn.
4. Remote tools are external-effect: claimed in one transaction, executed outside, resolved in another; a timeout marks `uncertain` (`agent.md` §6).
5. `tool_def_sha256` for a remote tool includes the server id **and URL**.
6. Remote tools are never exposed inbound and never run from jobs.
7. The Approve card shows the full args.

### Address policy (enforced at connection time)

1. Destinations: **https only**.
2. **Refused:** loopback, private-network, link-local, and IPv4-mapped IPv6 addresses.
3. `MCP_ALLOW_PRIVATE=1` permits those addresses and also permits `http://` to them, for local development.
4. Enforced **at connection time**, not by a one-off hostname check. A custom `httpx` transport:
   1. resolves the host;
   2. validates **every** returned address;
   3. connects to a validated IP while keeping the original hostname for SNI and certificate verification;
   4. does **not** follow redirects.
5. 30 s timeout; response capped at **1 MB**.

### First target

todogtd.com is the first outbound server the plan names.

## Tests that pin this

- MCP link lists role-filtered tools and executes an attributed write via a real `ClientSession` over `httpx.ASGITransport`.
- Revoked and deactivated links 404.
- Origin refused.
- `for_source("mcp")` excludes protected and remote tools.
- Outbound against a local FastMCP stub: discovery, prefixing, every call confirms, private address refused, fenced result.
- DNS rebinding: a stub resolver returns a public address first and a private one second; the connection is refused.

## Source

Build plan: §6 (all), §5 (`ToolSpec`, `for_source`, `tool_def_sha256`, confirmation), §1 (encryption), §2 (deactivation, system principal), Decisions (MCP), Risks 8, Verification.
