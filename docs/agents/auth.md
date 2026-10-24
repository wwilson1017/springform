# Login, sessions and users

**What this covers:** all of §2: the session cookie and why, CSRF, the auth tables, the system principal, first run and the setup token, password login and rate limits, Google OIDC and the linking rule, TOTP policy, the proxy constraint, invites and password reset, deactivation, `PREVIEW_MODE`, the frontend pieces, and the auth routes of the API block.
**Who reads it:** W1 (Login), the Step 1 minimal auth, anyone writing `current_user` / `require_admin` / `require_roles` call sites, and the frontend shell.

Code lives in `backend/core/auth/`: `service.py jwt.py deps.py router.py totp.py google.py invites.py mail.py bootstrap.py users_router.py csrf.py`.

## 1. What is lifted

From **CakeCRM** (already multi-user: admin/member, per-user TOTP with encrypted secret and bcrypt backup codes, hashed trusted-device cookie, `token_epoch` revocation, `require_admin`, account + IP rate limits, bcrypt timing equalizer):

| Donor | Lines | Likely Springform target (by file name; the plan fixes the folder, not the split) |
|---|---|---|
| `backend/core/auth.py` | 486 | `core/auth/service.py`, `jwt.py`, `deps.py` |
| `backend/core/auth_2fa.py` | 407 | `core/auth/totp.py` |
| `backend/users/service.py` | 395 | `core/auth/service.py` |
| `backend/users/bootstrap.py` | 231 | `core/auth/bootstrap.py` |
| `backend/users/router.py` | 155 | `core/auth/users_router.py` |
| `backend/gmail/oauth.py` (code exchange) | 86 | `core/auth/google.py` (exchange only) |
| todo-gtd `backend/signin.py` `_send` | — | `core/auth/mail.py` (Resend) |

Port **only SQL**: `%s` → `?`, `FOR UPDATE` → `transaction()`, `now()` → `now_iso()`. Budget ≈1,450 lifted / 650 new. `google.py` is new (~200).

## 2. Session

| Item | Contract |
|---|---|
| Token | HS256 JWT with claims `sub` (user id) and `pwd_epoch` (the user's `core_users.token_epoch` at issue). |
| Carrier | httpOnly cookie **`sf_session`**, `SameSite=Lax`, lifetime **12 h**. `secure=` follows the real request scheme (`TRUST_PROXY`). |
| Bearer | `Authorization: Bearer <jwt>` is also accepted, for tests and CLI. |
| Revocation | Bump `core_users.token_epoch`. A token whose `pwd_epoch` differs is rejected on the next request. |
| MCP | Uses its own tokens (`mcp.md`), not this session. |

Why a cookie: the Google callback is a top-level redirect; fetch-based SSE sends cookies for free; XSS cannot read an httpOnly cookie.

Dependencies (`deps.py`): `current_user`, `require_admin`, `require_roles(roles)` (used by `registry.mount()` with the manifest's roles; `authorization.md`).

The JWT signing key is the `SECRET_KEY` environment variable.

## 3. CSRF (`csrf.py`)

1. A state-changing `/api` request **authenticated by the cookie** must carry `Sec-Fetch-Site: same-origin` or `Sec-Fetch-Site: none`, **or** an `Origin` header equal to `PUBLIC_URL`.
2. Missing both → refused.
3. A request carrying **only** a bearer header is exempt.
4. A request carrying **both** a cookie and a bearer header is treated as cookie-authenticated (rule 1 applies).
5. Preflights (`OPTIONS`) are not authenticated and pass.

A refusal is **403** `{detail: "csrf"}`. State-changing means every method except `GET`, `HEAD` and `OPTIONS`.

## 4. Tables

All in the core init migration (Step 1).

```sql
core_users(
  id, email, name,
  role CHECK (role IN ('admin','member','system')),
  password_hash DEFAULT '!',          -- '!' never authenticates
  google_sub UNIQUE NULL,
  is_active, token_epoch, tz,
  invited_by, last_login_at, deactivated_at, …
)
-- plus a unique index on lower(trim(email))

core_totp                 -- per-user TOTP: encrypted secret, bcrypt backup codes (CakeCRM shape)
core_trusted_devices      -- hashed trusted-device cookie (CakeCRM shape)
core_login_tokens(token_hash PK, user_id, purpose CHECK (purpose IN ('invite','reset','setup')), expires_at, used_at)
core_login_attempts(key, at)   -- DB-backed rate limits; pruned hourly by core.login_attempts_prune
```

Open (pinned by the implementing workstream, which updates this doc): `core_totp` and `core_trusted_devices` columns are not listed in the plan (lift CakeCRM's shape). The "…" columns of `core_users` (e.g. `created_at`, `updated_at`).

### The system principal

One seeded row: `id=0`, `role='system'`, email `system@springform.local`, `password_hash='!'`. It can never authenticate: **login, Google, invite and MCP-link minting all reject `role='system'`**. It is excluded from user listings, notification recipients and "every active user" expansions. Full rules in `authorization.md` §7.

## 5. First run and the setup token

1. No "first visitor becomes admin".
2. On **every boot** while there is **no human user** in `core_users` (`WHERE role != 'system'`; not "an empty table", because the system row exists), `bootstrap.py` generates a fresh **setup token**, replacing any earlier one:
   - printed once in the log;
   - written to `/data/setup-token`, mode 0600;
   - `deploy/setup.sh` prints it at the end.
3. The setup page `/setup` requires the token (`POST /api/auth/setup`).
4. Admin creation happens under the write lock with a re-check that there is still no human user (`WHERE role != 'system'`, the same test as the bootstrap), and the token is consumed (`core_login_tokens` purpose `setup`).
5. After setup, `POST /api/auth/setup` returns **404** (also 404 for a wrong token).
6. The first admin is created by password or CLI only: `python -m backend.cli create-admin EMAIL`. Google is configured afterwards in Settings and linked on the admin's next Google sign-in.
7. The setup test runs against the real migrated, seeded database.

## 6. Password login and rate limits

1. `POST /api/auth/login {email, password}`. Wrong password and unknown email take equal time (bcrypt timing equalizer).
2. An invited user with `password_hash='!'` cannot log in by password.
3. Account and IP rate limits are DB-backed in `core_login_attempts(key, at)`; over the limit → **429**.
4. A user with TOTP enrolled completes a second step (TOTP code or backup code), unless a valid trusted-device cookie is present.

Open (pinned by the implementing workstream, which updates this doc): the limits (counts and windows) are not stated (lift CakeCRM's). The response when a TOTP step is required, and the TOTP verify route, are not in the API block.

## 7. Google sign-in (OIDC, `google.py`)

Flow: server-side authorization code + PKCE with `httpx` (the code exchange is CakeCRM `gmail/oauth.py`'s); `prompt=select_account`.

ID token checks, all required:

1. `google-auth` `id_token.verify_oauth2_token`;
2. `aud` equals our client id;
3. `iss` is `accounts.google.com` or `https://accounts.google.com`;
4. `exp` not passed;
5. `nonce` equals the one in the signed state cookie;
6. `email_verified == true`.

Configuration: client id and secret in encrypted `core_settings`. Redirect URI built from the `PUBLIC_URL` environment variable, **never the Host header**. Each install needs its own Google Cloud OAuth client (a Guide topic says how).

### Linking rule

1. A user whose `google_sub` is NULL is linked **automatically by email only when Google is authoritative for that address**:
   - the email is `@gmail.com` or `@googlemail.com`; or
   - the token's `hd` claim equals the email's domain (Google Workspace).
2. For any other address (a Google account registered with a third-party email), automatic linking is **refused**. The user links from an authenticated session: the invite link (which proves control of the mailbox) → set a password, or Settings → Security → **"Link Google"**, which runs the same OIDC flow and stores `sub`.
3. After linking, the account is identified **by `sub` only** (Google says email can change).
4. A sign-in whose `sub` matches no row is refused, even if the email matches an existing linked user.
5. Not invited → redirect to `/login?error=not_invited`. **Never auto-create** a user.
6. `role='system'` is rejected.

### TOTP policy

A Google sign-in **skips local TOTP**. Springform does not verify that the Google account used 2-step verification. The admin setting **`auth.require_totp_for_google`** (default off) adds the local TOTP step for installs that want it.

Open (pinned by the implementing workstream, which updates this doc): the Google route paths are not stated. The plan refers to `google/start` (and a callback); `/api/auth/google/start` and `/api/auth/google/callback` are the likely shape. Settings has a "Test sign-in" action (Risks, item 6) with no stated contract.

## 8. Proxy

1. `TRUST_PROXY=1` → uvicorn `--proxy-headers --forwarded-allow-ips='*'`.
2. Cookie `secure=` follows the real scheme.
3. Startup warns if `PUBLIC_URL` is https but requests are not.
4. **Constraint, documented and enforced by `deploy/compose.yml`:** with `TRUST_PROXY=1` the app port is bound only on the compose network (never published), so forwarded headers can only come from Caddy (`deploy.md`).

## 9. Invites and password reset

1. An admin adds email, name, role → a `core_users` row with `password_hash='!'` (never authenticates) and `invited_by`.
2. An invite token (`core_login_tokens` purpose `invite`, **1 h**) is mailed via Resend (`RESEND_API_KEY` + `MAIL_FROM`; lift todo-gtd `signin._send`) **or** shown as a copyable link.
3. The invitee sets a password or signs in with Google (subject to the linking rule).
4. The same token mechanism serves "forgot password" (purpose `reset`).
5. Step 1 ships the copyable link only (no mail).

Open (pinned by the implementing workstream, which updates this doc): invite, accept, reset and user-admin routes are not stated (shape to be pinned by W1). Whether an expired invite can be re-sent or the token is single-use beyond `used_at`.

## 10. Deactivation

Deactivating a user:

1. bumps `token_epoch` (kills every session);
2. revokes the user's MCP links (`core_agent_mcp_links.revoked_at`) and trusted devices;
3. hides the user's private todos (an admin may transfer them to another owner); team todos stay in place;
4. sets `is_active` false and `deactivated_at`.

Revoked and deactivated MCP links return 404 (`mcp.md`).

## 11. `PREVIEW_MODE`

1. `PREVIEW_MODE=1` seeds `preview-admin@example.com` and `preview-member@example.com`.
2. `LoginPage` shows a role picker → `POST /api/auth/preview {role}`.
3. `google/start` redirects to a local stub, so Playwright covers the Google path.
4. **Startup refuses preview mode if real secrets are present**: `ENCRYPTION_KEY` or `RESEND_API_KEY` set (non-empty) in the environment, or any `core_settings` row with `is_secret=1`. The check runs after migrations, because it reads `core_settings`.
5. The factory reset is allowed in preview mode (`database-and-transactions.md` §6).

## 12. Frontend (`frontend/src/core/auth/`)

| Piece | Source | Contract |
|---|---|---|
| `AuthContext.tsx` | CakeCRM (227) | Drop sessionStorage and BroadcastChannel; `GET /api/me` with the cookie. |
| `LoginPage.tsx` | CakeCRM (181) | Password form + Google button + preview role picker; shows `?error=not_invited`. |
| `SetupPage` | new | Token field + email, name, password. |
| `InvitePage` | new | Accept an invite: set a password or sign in with Google. |
| Security settings card | new | 2FA enrol; "Link Google". |
| Users admin card | new | Invite, role, deactivate, transfer. |

W1 contributes the Security and Users cards through the settings registry W6 defines; it does not edit `settings/`.

## 13. API (auth rows of the API block)

```
GET  /api/auth/status  -> {setup_required: bool, google: bool, preview: bool}
POST /api/auth/setup   {token, email, name, password} -> 200 {user} + cookie; 404 when setup is not required or the token is wrong
POST /api/auth/login   {email, password} -> 200 {user} + cookie; 401 {detail:"invalid_credentials"}; 429 when rate-limited
POST /api/auth/logout  -> 204, clears the cookie
POST /api/auth/preview {role} -> 200 {user} + cookie (PREVIEW_MODE only, else 404)
GET  /api/me           -> {id, email, name, role: "admin"|"member", tz}; 401 when not signed in
Errors: `{detail}`; 401 not signed in, 403 denied, 404 missing or not readable, 422 invalid.
```

Routes named by the plan, shape to be pinned by W1: Google start/callback, invite create/accept, password reset, TOTP enrol/verify, trusted devices, users admin (list, role, deactivate, transfer), "Link Google".

## Tests that pin this

- Setup requires the token, consumes it, and 404s afterwards; the setup test runs against the real migrated, seeded database.
- Invite hash `'!'` can't log in.
- Password login with equal-time wrong-password.
- Account + IP limits via `core_login_attempts`.
- TOTP enrol/verify/replay/backup/trusted device.
- Google callback with a mocked token endpoint: invited signs in and gets linked, uninvited refused, wrong `aud`/`iss`/`nonce`/unverified email refused, mismatched `google_sub` refused.
- Epoch bump kills the cookie.
- `require_admin` 403.
- CSRF: cookie + cross-site POST refused, cookie + no fetch metadata refused, bearer-only passes.
- Deactivation hides private todos; revoked and deactivated MCP links 404.
- Playwright: pick role → … → password login → enable 2FA (pyotp) → Google login via the preview stub.

## Source

Build plan: §2 (all), Decisions (Login), Step 1 (minimal auth), Step 2 W1, Risks 6, Verification. API block (orchestrator).
