# MCP: inbound links and outbound servers

**What this covers:** §6. Inbound: a per-user MCP link that is an API key for that user, immediate writes, exclusions, the HTTP rules lifted from todo-gtd, the SDK choice, URL forms. Outbound: the servers table, discovery and refresh, naming, every call confirms, untrusted fencing, the address policy enforced at connection time, and the DNS-rebinding test.
**Who reads it:** W14 (MCP server), W15 (MCP client), W9/W12 (registry and confirmation), the MCP settings cards.

Code: inbound in `backend/core/mcp/` (`links.py`, `server.py`, `router.py`, `ratelimit.py`, `startup.py`), running tools through `backend/core/agent/execute.py`; outbound in `backend/core/agent/mcp_client.py`. Both work with zero AI keys.

## 1. Inbound (`backend/core/mcp/`)

### Table

```sql
core_agent_mcp_links(id, user_id, token_hash UNIQUE, label, created_at, last_used_at, revoked_at)
```

Migration `20261020000520_core_mcp_links.sql`. The token is `secrets.token_urlsafe(32)` (256 bits, 43 URL-safe characters), returned **once** at minting; only its sha256 is stored. `last_used_at` is written at most once a minute per link.

### A link is an API key for its user (decided)

1. `call_tool` **executes immediately**, as the link's user, through `execute.run_tool(user, spec, args, source="mcp")`: the same path the chat loop and the approval step use, so targets are authorized for write and a local write runs in one transaction.
2. Every call is logged in `core_agent_tool_runs` with `source='mcp'`, the link's `user_id`, and no conversation.
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
4. `list_tools` returns JSON-schema `Tool`s with `readOnlyHint = not writes`. A call to a tool not in the user's list is an error result and runs nothing.
5. A result is the stored JSON as one text block; a failure is `isError` with `{status, error}` (`error`, or `uncertain` for an external effect that may have happened).

### HTTP rules (lifted from todo-gtd `backend/mcp_server.py` HTTP section and `backend/ratelimit.py`)

The endpoint lives in `backend/core/mcp/router.py` as plain ASGI routes on the discovered `router`. They sit outside `/api` and outside the OpenAPI schema, so the contract test's unauthenticated allow-list (which covers `/api` routes) does not list them; these rules and `test_mcp_links.py` are their guard.

| Request | Response |
|---|---|
| Any request carrying an `Origin` header | **403**, checked first. AI clients call from a server or a desktop app and send none. |
| Path token `/mcp/<token>` that is unknown, revoked or deactivated | **404**, never 401. |
| Bearer `/mcp` with a bad or missing token | **401** with `WWW-Authenticate: Bearer` (no resource metadata: there is no OAuth server). |
| `/.well-known/…`, `/register`, `/authorize`, `/token`, any method | **404** (no OAuth; a client finds no sign-in and uses the link as is). |
| More than **600 requests/min per link** | **429**, `Retry-After: 60`. |
| More than **60 wrong tokens per 10 min from one address** | **429**, `Retry-After: 600`. Only misses are charged and a valid link is always served, so one bad client behind a shared address cannot lock others out. A request with no token at all is not a miss. |
| Declared body over **4 MB** | **413**; the SDK caps a body sent without a length at the same size. |
| Anything else with a live link (POST, and GET/DELETE as the transport answers them) | Handed to the SDK as the link's user. |

Doc drift fixed here: an earlier version gave the per-IP limit as `IPRateLimiter(window=60, max_hits=600)`; in the donor that is the per-link call limit, and the per-address limit is the wrong-token one (`window=600, max_hits=60`).

The access log shows `/mcp/***` instead of the token (`startup.py`, after todo-gtd `backend/logscrub.py`).

The plan cites the donor section as lines ~700–946; at the recorded donor sha it is lines 832–946 (`source-map.md`).

### SDK

The `mcp` SDK (pinned `mcp==2.3.0`, the version todo-gtd's FastMCP resolves) **low-level `Server`** with `StreamableHTTPSessionManager(stateless=True, json_response=True)`. A fresh manager serves each request (`server.handle`), so nothing starts from the app lifespan; the router sets the link's user in a context variable first. (The todo-gtd donor uses FastMCP; only its HTTP section is lifted.) The SDK's client speaks `httpx2`, so the tests drive it through `httpx2.ASGITransport`.

### URL forms

| Client | URL |
|---|---|
| claude.ai custom connector, Claude Desktop | `https://host/mcp/<token>` |
| Claude Code | `claude mcp add --transport http springform https://host/mcp/<token>`, or `https://host/mcp` + `Authorization: Bearer <token>` |

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

Open (pinned by the implementing workstream, which updates this doc): the hourly discovery job is not in §11's core job list; its job name and whether it runs through the scheduler are not stated.

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

- MCP link lists role-filtered tools and executes an attributed write via a real `ClientSession` over `httpx2.ASGITransport` (`test_mcp_links.py`).
- Revoked and deactivated links 404; bearer 401; Origin 403; no OAuth discovery; rate limits and the body cap; a system-principal mint refused.
- `for_source("mcp")` excludes protected and remote tools.
- Outbound against a local FastMCP stub: discovery, prefixing, every call confirms, private address refused, fenced result.
- DNS rebinding: a stub resolver returns a public address first and a private one second; the connection is refused.

## Source

Build plan: §6 (all), §5 (`ToolSpec`, `for_source`, `tool_def_sha256`, confirmation), §1 (encryption), §2 (deactivation, system principal), Decisions (MCP), Risks 8, Verification.
