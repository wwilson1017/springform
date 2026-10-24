"""User accounts and credentials: lookup, creation, password checks, login rate limits.

Two invariants carry weight elsewhere:
- Bcrypt only, failing closed. `verify_password` requires a bcrypt prefix and returns False for
  anything else, so a `'!'` hash (an invited user who has not set a password, the system
  principal) can never authenticate.
- Emails are stored normalized (`normalize_email`), and the unique index on
  `lower(trim(email))` is the authority on duplicates, not a pre-check.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import bcrypt as _bcrypt

from backend.core import clock, db
from backend.core.errors import Conflict, Invalid, NotFound

ROLES = ("admin", "member")
BCRYPT_ROUNDS = 12  # the test suite lowers this
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72  # bcrypt ignores everything past 72 bytes
TOKEN_SECONDS = 3600  # invite and reset links
ACCOUNT_LIMIT = (10, 300)  # attempts per window (seconds), per email
IP_LIMIT = (50, 300)  # higher: one office shares a NAT address
_WS = " \t\n\r\f\v"  # ASCII whitespace only; str.strip() would also eat a pasted NBSP
_COLUMNS = (
    "id, email, name, role, tz, is_active, token_epoch, password_hash, google_sub, invited_by, last_login_at, "
    "deactivated_at, created_at"
)

# Called inside the deactivating transaction, after the user row is marked: later workstreams
# append here (MCP links, private todos). Same rules as a sync hook: cheap, no network, no
# transaction() of their own; raising rolls the deactivation back.
ON_DEACTIVATE: list[Callable[[db.Conn, int], None]] = []


class InvalidCredentials(Exception):
    """Unknown email, wrong password, or an account that cannot sign in. One answer for all."""


class RateLimited(Exception):
    pass


def normalize_email(raw: str) -> str:
    return (raw or "").strip(_WS).lower()


def validate_password(plain: str) -> None:
    if len(plain or "") < MIN_PASSWORD_LENGTH:
        raise Invalid(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(plain.encode()) > MAX_PASSWORD_BYTES:
        raise Invalid(f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def has_password(stored: str | None) -> bool:
    return bool(stored) and stored.startswith(("$2a$", "$2b$", "$2y$"))


def token_hash(token: str) -> str:
    """How every one-time token (setup, invite, reset, trusted device) is stored: sha256, never raw."""
    return hashlib.sha256((token or "").encode()).hexdigest()


def verify_password(plain: str, stored: str | None) -> bool:
    """Fails closed on anything that is not a bcrypt hash; no plaintext comparison anywhere."""
    if not has_password(stored):
        return False
    try:
        return _bcrypt.checkpw(plain.encode(), stored.encode())
    except ValueError:
        return False


_dummy_hashes: dict[int, str] = {}


def spend_dummy_verify() -> None:
    """Burn one bcrypt check, so an unknown email costs what a known one does."""
    if BCRYPT_ROUNDS not in _dummy_hashes:
        _dummy_hashes[BCRYPT_ROUNDS] = hash_password("springform-timing-equalizer")
    verify_password("x", _dummy_hashes[BCRYPT_ROUNDS])


def get_user(user_id: int) -> dict | None:
    """One user row including the password hash (internal callers only; never return it)."""
    return db.one(f"SELECT {_COLUMNS} FROM core_users WHERE id = ?", (user_id,))


def get_user_by_email(email: str) -> dict | None:
    return db.one(f"SELECT {_COLUMNS} FROM core_users WHERE lower(trim(email)) = ?", (normalize_email(email),))


def human_users_exist(conn: db.Conn) -> bool:
    return conn.execute("SELECT 1 FROM core_users WHERE role != 'system' LIMIT 1").fetchone() is not None


def create_user_in(
    conn: db.Conn, email: str, name: str, role: str, password: str | None = None, invited_by: int | None = None
) -> dict:
    """A new account. Without a password it gets the `'!'` hash and cannot sign in yet."""
    email = normalize_email(email)
    local, _, domain = email.partition("@")
    if not local or not domain or any(c.isspace() for c in email):
        raise Invalid("A valid email address is required.")
    if role not in ROLES:
        raise Invalid(f"Role must be one of: {', '.join(ROLES)}.")
    if password is not None:
        validate_password(password)
    now = clock.now_iso()
    try:
        cur = conn.execute(
            """INSERT INTO core_users (email, name, role, password_hash, invited_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (email, (name or "").strip(), role, hash_password(password) if password else "!", invited_by, now, now),
        )
    except db.sqlite3.IntegrityError as e:
        if "UNIQUE" not in str(e):
            raise
        raise Conflict("A user with that email already exists.") from None
    return dict(conn.execute(f"SELECT {_COLUMNS} FROM core_users WHERE id = ?", (cur.lastrowid,)).fetchone())


def over_limit_in(conn: db.Conn, key: str, limit: int, window: int) -> bool:
    """Sliding window over core_login_attempts; an attempt under the limit is recorded."""
    n = conn.execute("SELECT count(*) FROM core_login_attempts WHERE key = ? AND at > ?", (key, clock.ago(window))).fetchone()[0]
    if n >= limit:
        return True
    conn.execute("INSERT INTO core_login_attempts (key, at) VALUES (?, ?)", (key, clock.now_iso()))
    return False


def authenticate(email: str, password: str, ip: str) -> dict:
    """The user row for a correct email + password. Raises RateLimited or InvalidCredentials.

    Limits are on both the account (what an attacker has to grind) and the source address.
    Every failure path spends one bcrypt check, so timing does not reveal which emails exist."""
    with db.transaction() as conn:
        account = over_limit_in(conn, f"acct:{normalize_email(email)}", *ACCOUNT_LIMIT)
        address = over_limit_in(conn, f"ip:{ip}", *IP_LIMIT)
    if account or address:
        raise RateLimited()
    user = get_user_by_email(email)
    if not user or not user["is_active"] or user["role"] == "system" or not has_password(user["password_hash"]):
        spend_dummy_verify()
        raise InvalidCredentials()
    if not verify_password(password, user["password_hash"]):
        raise InvalidCredentials()
    return user


def bump_token_epoch_in(conn: db.Conn, user_id: int) -> int:
    """End every session this user holds. Returns the new epoch."""
    row = conn.execute(
        "UPDATE core_users SET token_epoch = token_epoch + 1, updated_at = ? WHERE id = ? RETURNING token_epoch",
        (clock.now_iso(), user_id),
    ).fetchone()
    return int(row[0]) if row else 0


def prune_login_attempts(cancel=None) -> None:
    """Job core.login_attempts_prune: attempts older than a day count toward nothing; expired
    invite/reset links and trusted devices are dropped too."""
    with db.transaction() as conn:
        conn.execute("DELETE FROM core_login_attempts WHERE at < ?", (clock.ago(86400),))
        conn.execute("DELETE FROM core_login_tokens WHERE purpose != 'setup' AND expires_at < ?", (clock.ago(86400),))
        conn.execute("DELETE FROM core_trusted_devices WHERE expires_at < ?", (clock.now_iso(),))


# ── Invite and reset links ───────────────────────────────────────────────────


def issue_token_in(conn: db.Conn, user_id: int, purpose: str, created_by: int | None = None) -> str:
    """A fresh one-hour link token (`invite` or `reset`); the user's unused one of that purpose stops working."""
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM core_login_tokens WHERE user_id = ? AND purpose = ? AND used_at IS NULL", (user_id, purpose))
    conn.execute(
        """INSERT INTO core_login_tokens (token_hash, user_id, purpose, expires_at, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (token_hash(token), user_id, purpose, clock.later(TOKEN_SECONDS), created_by, clock.now_iso()),
    )
    return token


def token_user_in(conn: db.Conn, token: str, purpose: str) -> dict | None:
    """The active human account a live, unused token of `purpose` belongs to (pass db.get_conn() to just look)."""
    row = conn.execute(
        """SELECT u.* FROM core_login_tokens t JOIN core_users u ON u.id = t.user_id
            WHERE t.token_hash = ? AND t.purpose = ? AND t.used_at IS NULL AND t.expires_at > ?
              AND u.is_active = 1 AND u.role != 'system'""",
        (token_hash(token), purpose, clock.now_iso()),
    ).fetchone()
    return dict(row) if row else None


def spend_token_in(conn: db.Conn, token: str, purpose: str) -> dict | None:
    """Like token_user_in, and the token is used up."""
    row = token_user_in(conn, token, purpose)
    if row:
        conn.execute("UPDATE core_login_tokens SET used_at = ? WHERE token_hash = ?", (clock.now_iso(), token_hash(token)))
    return row


# ── User administration ──────────────────────────────────────────────────────


def admin_view(row: dict, totp_enabled: bool = False) -> dict:
    """A user as the Users card shows it. Never the hash or the Google subject."""
    return {
        "id": row["id"], "email": row["email"], "name": row["name"], "role": row["role"], "tz": row["tz"],
        "is_active": bool(row["is_active"]),
        "invite_pending": not has_password(row["password_hash"]) and not row["google_sub"],
        "has_password": has_password(row["password_hash"]), "google_linked": bool(row["google_sub"]),
        "totp_enabled": totp_enabled, "invited_by": row["invited_by"], "last_login_at": row["last_login_at"],
        "deactivated_at": row["deactivated_at"], "created_at": row["created_at"],
    }


def list_users(active: bool | None = None) -> list[dict]:
    """Every human account (never the system principal), active first, then by name."""
    rows = db.rows(
        """SELECT u.*, coalesce(t.enabled, 0) AS totp FROM core_users u LEFT JOIN core_totp t ON t.user_id = u.id
            WHERE u.role != 'system' AND (? IS NULL OR u.is_active = ?)
            ORDER BY u.is_active DESC, lower(u.name), u.email""",
        (active, active),
    )
    return [admin_view(r, bool(r["totp"])) for r in rows]


def human_in(conn: db.Conn, user_id: int) -> dict:
    """A human account's row on `conn`; NotFound for the system principal or an unknown id."""
    row = conn.execute(f"SELECT {_COLUMNS} FROM core_users WHERE id = ? AND role != 'system'", (user_id,)).fetchone()
    if row is None:
        raise NotFound()
    return dict(row)


def validate_tz(tz: str | None) -> str | None:
    if not tz:
        return None
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise Invalid(f"Unknown time zone: {tz}") from None
    return tz


def _guard_last_admin_in(conn: db.Conn, row: dict) -> None:
    """The install keeps at least one active admin who can sign in (a pending invite cannot);
    demoting or deactivating that last one is refused. The write lock makes count + write atomic."""
    if row["role"] != "admin" or not row["is_active"]:
        return
    others = conn.execute(
        """SELECT count(*) FROM core_users WHERE role = 'admin' AND is_active = 1 AND id != ?
             AND (password_hash != '!' OR google_sub IS NOT NULL)""",
        (row["id"],),
    ).fetchone()[0]
    if not others:
        raise Conflict("last_admin")


def update_user_in(conn: db.Conn, user_id: int, changes: dict) -> dict:
    """Apply `changes` (any of name, role, tz) to a human account."""
    row = human_in(conn, user_id)
    if "role" in changes and changes["role"] not in ROLES:
        raise Invalid(f"Role must be one of: {', '.join(ROLES)}.")
    if changes.get("role", row["role"]) != row["role"]:
        _guard_last_admin_in(conn, row)
    if "tz" in changes:
        changes["tz"] = validate_tz(changes["tz"])
    if "name" in changes:
        changes["name"] = (changes["name"] or "").strip()
    for col in ("name", "role", "tz"):
        if col in changes:
            conn.execute(f"UPDATE core_users SET {col} = ?, updated_at = ? WHERE id = ?", (changes[col], clock.now_iso(), user_id))
    return human_in(conn, user_id)


def deactivate_in(conn: db.Conn, user_id: int) -> dict:
    """End every session, forget trusted devices and unused invite/reset links, then run ON_DEACTIVATE."""
    row = human_in(conn, user_id)
    _guard_last_admin_in(conn, row)
    now = clock.now_iso()
    conn.execute(
        """UPDATE core_users SET is_active = 0, deactivated_at = coalesce(deactivated_at, ?),
                  token_epoch = token_epoch + 1, updated_at = ? WHERE id = ?""",
        (now, now, user_id),
    )
    conn.execute("DELETE FROM core_trusted_devices WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM core_login_tokens WHERE user_id = ? AND used_at IS NULL", (user_id,))
    for fn in ON_DEACTIVATE:
        fn(conn, user_id)
    return human_in(conn, user_id)


def reactivate_in(conn: db.Conn, user_id: int) -> dict:
    human_in(conn, user_id)
    conn.execute(
        "UPDATE core_users SET is_active = 1, deactivated_at = NULL, updated_at = ? WHERE id = ?", (clock.now_iso(), user_id)
    )
    return human_in(conn, user_id)


def set_password_in(conn: db.Conn, user_id: int, hashed: str) -> int:
    """Store a new bcrypt hash (hash it before the transaction: bcrypt is slow), end every other
    session and forget trusted devices. Returns the new token epoch for the caller's fresh cookie."""
    conn.execute("UPDATE core_users SET password_hash = ? WHERE id = ?", (hashed, user_id))
    conn.execute("DELETE FROM core_trusted_devices WHERE user_id = ?", (user_id,))
    return bump_token_epoch_in(conn, user_id)
