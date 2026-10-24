# Login, sessions and users

**What this covers:** all of §2: the session cookie and why, CSRF, the auth tables, the system principal, first run and the setup token, password login and rate limits, Google OIDC and the linking rule, TOTP policy, the proxy constraint, invites and password reset, deactivation, `PREVIEW_MODE`, the frontend pieces, and the auth routes of the API block.
**Who reads it:** W1 (Login), the Step 1 minimal auth, anyone writing `current_user` / `require_admin` / `require_roles` call sites, and the frontend shell.

Code lives in `backend/core/auth/`: `service.py jwt.py deps.py router.py totp.py trusted.py google.py invites.py mail.py bootstrap.py users_router.py csrf.py`, plus `backend/cli.py` (`create-admin`).

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

Dependencies (`deps.py`): `current_user`, `require_admin`, `require_roles(roles)` (used by `registry.mount_app()` with the manifest's roles; `authorization.md`).

The JWT signing key is the `SECRET_KEY` environment variable, else `<DATA_DIR>/.secret-key`, generated at first boot.

## 3. CSRF (`csrf.py`)

1. A state-changing `/api` request **authenticated by the cookie** must carry `Sec-Fetch-Site: same-origin` or `Sec-Fetch-Site: none`, **or** an `Origin` header equal to `PUBLIC_URL`.
2. Missing both → refused.
3. A request carrying **only** a bearer header is exempt.
4. A request carrying **both** a cookie and a bearer header is treated as cookie-authenticated (rule 1 applies).
5. Preflights (`OPTIONS`) are not authenticated and pass.

A refusal is **403** `{detail: "csrf_refused"}`. State-changing means every method except `GET`, `HEAD` and `OPTIONS`.

## 4. Tables

All in the core init migration (Step 1).

```sql
core_users(
  id, email, name,
  role CHECK (role IN ('admin','member','system')),
  password_hash DEFAULT '!',          -- '!' never authenticates
  google_sub UNIQUE NULL,
  is_active, token_epoch, tz,
  invited_by, last_login_at, deactivated_at, created_at, updated_at
)
-- plus a unique index on lower(trim(email))

core_totp(user_id PK, enabled, secret_enc, backup_codes JSON, last_used_at, created_at, updated_at)
  -- secret encrypted; backup codes are bcrypt hashes; last_used_at holds the last accepted step (replay slot)
core_trusted_devices(token_hash PK, user_id, label, expires_at, created_at)
core_login_tokens(token_hash PK, user_id NULL, purpose CHECK (purpose IN ('invite','reset','setup')),
                  expires_at NULL, used_at, created_by, created_at)
  -- the setup token has no user and no expiry
core_login_attempts(key, at)   -- DB-backed rate limits; pruned hourly by core.login_attempts_prune
```

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
3. Account and IP rate limits are DB-backed in `core_login_attempts(key, at)`; over the limit → **429** `{detail: "rate_limited"}`.
4. A user with TOTP enrolled completes a second step (TOTP code or backup code), unless a valid trusted-device cookie is present. Login then answers **200** `{totp_required: true, challenge}` with no cookie, and `POST /api/auth/login/totp {challenge, code | backup_code, trust_device}` finishes it.
5. A trusted device is the `sf_trusted` cookie (30 days, path `/api/auth`).

| Limit | Value |
|---|---|
| Login, per email | 10 per 5 min |
| Login, per IP | 50 per 5 min |
| TOTP checks, per user | 5 per 5 min; the challenge lasts 5 min |
| Forgot password | 3 per hour per email, 20 per hour per IP |
| Password change, per user | 5 per 5 min |

## 7. Google sign-in (OIDC, `google.py`)

Flow: server-side authorization code + PKCE with `httpx` (the code exchange is CakeCRM `gmail/oauth.py`'s); `prompt=select_account`.

ID token checks, all required:

1. `google-auth` `id_token.verify_oauth2_token`;
2. `aud` equals our client id;
3. `iss` is `accounts.google.com` or `https://accounts.google.com`;
4. `exp` not passed;
5. `nonce` equals the one in the signed state cookie;
6. `email_verified == true`.

Configuration: client id and secret in encrypted `core_settings` (`auth.google_client_id`, `auth.google_client_secret`), written by `PUT /api/auth/google/config`. Redirect URI built from the `PUBLIC_URL` environment variable, **never the Host header**. Each install needs its own Google Cloud OAuth client (a Guide topic says how).

### Linking rule

1. A user whose `google_sub` is NULL is linked **automatically by email only when Google is authoritative for that address**:
   - the email is `@gmail.com` or `@googlemail.com`; or
   - the token's `hd` claim equals the email's domain (Google Workspace).
2. For any other address (a Google account registered with a third-party email), automatic linking is **refused**. The user links in one of two ways. On the invite page, the Google button links whichever Google account they pick, because the invite token proved control of the mailbox. Otherwise they sign in and use Settings → Security → **"Link Google"** (`GET /api/auth/google/start?link=1`), which runs the same OIDC flow and stores `sub`.
3. After linking, the account is identified **by `sub` only** (Google says email can change).
4. A sign-in whose `sub` matches no row is refused, even if the email matches an existing linked user.
5. Not invited → redirect to `/login?error=not_invited`. **Never auto-create** a user.
6. `role='system'` is rejected.

### TOTP policy

A Google sign-in **skips local TOTP**. Springform does not verify that the Google account used 2-step verification. The admin setting **`auth.require_totp_for_google`** (default off) adds the local TOTP step for installs that want it.

Google routes:

```
GET  /api/auth/google/start[?link=1 | ?invite=<token>]   redirect to Google
GET  /api/auth/google/callback
GET  /api/auth/google                 the caller's link state
POST /api/auth/google/unlink
GET  /api/auth/google/config          (admin)
PUT  /api/auth/google/config          (admin) client id and secret
POST /api/auth/google/test            (admin) checks the config locally, without contacting Google
```

A failure redirects with `error=` one of `not_invited`, `link_required`, `google_mismatch`, `google_failed` or `google_not_configured`.

## 8. Proxy

1. `TRUST_PROXY=1` → uvicorn `--proxy-headers --forwarded-allow-ips='*'`.
2. Cookie `secure=` follows the real scheme.
3. Startup warns if `PUBLIC_URL` is https but requests are not.
4. **Constraint, documented and enforced by `deploy/compose.yml`:** with `TRUST_PROXY=1` the app port is bound only on the compose network (never published), so forwarded headers can only come from Caddy (`deploy.md`).

## 9. Invites and password reset

1. An admin adds email, name, role → a `core_users` row with `password_hash='!'` (never authenticates) and `invited_by`.
2. An invite token (`core_login_tokens` purpose `invite`, **1 h**) makes the link `PUBLIC_URL/invite/<token>`. The link is always returned to the admin to copy, and is also mailed via Resend when `RESEND_API_KEY` and `MAIL_FROM` are set.
3. The invitee sets a password or presses Google (the linking rule's invite case).
4. The same token mechanism serves "forgot password" (purpose `reset`, a one-hour `PUBLIC_URL/reset-password/<token>` link). `POST /api/auth/forgot` answers 202 whether or not the account exists.
   Without mail nothing is sent, so an admin issues the same `reset` link for an active member (`POST /api/auth/users/{id}/reset-link`) and passes it on; it is also mailed when mail is configured, and `mailed` says whether Resend accepted it.
5. Links are single use. Resending an invite issues a new link and the old one stops working.
6. A reset or a password change ends every other session and forgets trusted devices. Accepting an invite or resetting a password ends like a password sign-in: a session, or the TOTP challenge.

```
POST  /api/auth/users                         (admin) invite -> {user, invite_url, mailed}
POST  /api/auth/users/{id}/resend-invite      (admin)
POST  /api/auth/users/{id}/reset-link         (admin) -> {reset_url, mailed}; 404 for an unknown, system or deactivated user
GET   /api/auth/users                         (admin)
PATCH /api/auth/users/{id}                    (admin) name, role, tz
POST  /api/auth/users/{id}/deactivate         (admin)
POST  /api/auth/users/{id}/reactivate         (admin)
GET   /api/auth/invite/{token}                the invite's details
POST  /api/auth/invite/{token}                accept: set a password
POST  /api/auth/forgot                        202
POST  /api/auth/reset
POST  /api/auth/password                      change the caller's password
PATCH /api/me
GET   /api/auth/totp; POST /api/auth/totp/enrol, /confirm, /disable
GET   /api/auth/trusted-devices; DELETE /api/auth/trusted-devices
```

## 10. Deactivation

Deactivating a user:

1. bumps `token_epoch` (kills every session);
2. deletes the user's trusted devices and unused invite and reset links;
3. will revoke the user's MCP links (`core_agent_mcp_links.revoked_at`) once MCP exists; nothing registers that yet;
4. sets `is_active` false and `deactivated_at`, then runs the `ON_DEACTIVATE` hooks.

Private todos are hidden because an inactive user fails `can_read`; an admin may transfer them with `POST /api/todos/transfer`. Team todos stay in place. Deactivating, or demoting, the last active admin who can sign in is refused with **409** `last_admin`.

Revoked and deactivated MCP links return 404 (`mcp.md`).

## 11. `PREVIEW_MODE`

1. `PREVIEW_MODE=1` seeds `preview-admin@example.com` and `preview-member@example.com`, each with a random password nobody knows, so the Users card shows them as signed up (not invite pending) and the last-admin guard counts them.
2. `LoginPage` shows a role picker → `POST /api/auth/preview {role}`.
3. `google/start` redirects to a local stub, so Playwright covers the Google path.
4. **Startup refuses preview mode if real secrets are present**: `ENCRYPTION_KEY` or `RESEND_API_KEY` set (non-empty) in the environment, or any `core_settings` row with `is_secret=1`. The check runs after migrations, because it reads `core_settings`.
5. The factory reset is allowed in preview mode (`database-and-transactions.md` §6).

## 12. Frontend (`frontend/src/core/auth/`)

| Piece | Source | Contract |
|---|---|---|
| `AuthContext.tsx` | CakeCRM (227) | Drop sessionStorage and BroadcastChannel; `GET /api/me` with the cookie. |
| `LoginPage.tsx` | CakeCRM (181) | Password form, "Continue with Google" (a plain link: `GET /api/auth/google/start`), preview role picker, "Forgot password?" mode, a message for every `?error=` code, and `#totp_challenge=` from the Google callback. |
| `ChallengeStep.tsx` | CakeCRM | The 2FA step (code or backup code, "Trust this browser"), shared by the login, invite and reset pages. |
| `SetupPage` | new | Token field + email, name, password. |
| `InvitePage`, `ResetPasswordPage` | new | Public routes `/invite/:token` and `/reset-password/:token` from `routes.tsx`. A 401 on these pages is an answer, not an expired session (`core/api/client.ts`). |
| `settingsCards.ts` | new | Sections **Account** (order 5, everyone: Profile, Security), **Users** (30, admins) and **Sign-in** (40, admins: Google client, redirect URI, Test, `require_totp_for_google`). Security holds password change, 2FA enrol/disable, trusted browsers and Link/Unlink Google. |

The Link Google round-trip lands on `/settings?google=linked` or `?google_error=<code>`; Settings redirects to its first section and drops the query, so `settingsCards.ts` reads it once at page load and shows a toast.

W1 contributes these cards through the settings registry W6 defines; it does not edit `settings/`.

## 13. API (auth rows of the API block)

```
GET  /api/auth/status  -> {setup_required: bool, google: bool, preview: bool}
POST /api/auth/setup   {token, email, name, password} -> 200 {user} + cookie; 404 when setup is not required or the token is wrong
POST /api/auth/login   {email, password} -> 200 {user} + cookie, or 200 {totp_required: true, challenge} with no cookie; 401 {detail:"invalid_credentials"}; 429 {detail:"rate_limited"}
POST /api/auth/logout  -> 204, clears the cookie
POST /api/auth/preview {role} -> 200 {user} + cookie (PREVIEW_MODE only, else 404)
GET  /api/me           -> {id, email, name, role: "admin"|"member", tz}; 401 when not signed in
Errors: `{detail}`; 401 not signed in, 403 denied, 404 missing or not readable, 422 invalid.
```

The rest of the auth routes are listed in §6, §7 and §9.

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
