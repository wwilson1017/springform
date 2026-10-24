"""User accounts and credentials: lookup, creation, password checks, login rate limits.

Two invariants carry weight elsewhere:
- Bcrypt only, failing closed. `verify_password` requires a bcrypt prefix and returns False for
  anything else, so a `'!'` hash (an invited user who has not set a password, the system
  principal) can never authenticate.
- Emails are stored normalized (`normalize_email`), and the unique index on
  `lower(trim(email))` is the authority on duplicates, not a pre-check.
"""

from __future__ import annotations

import bcrypt as _bcrypt

from backend.core import clock, db
from backend.core.errors import Conflict, Invalid

ROLES = ("admin", "member")
BCRYPT_ROUNDS = 12  # the test suite lowers this
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72  # bcrypt ignores everything past 72 bytes
ACCOUNT_LIMIT = (10, 300)  # attempts per window (seconds), per email
IP_LIMIT = (50, 300)  # higher: one office shares a NAT address
_WS = " \t\n\r\f\v"  # ASCII whitespace only; str.strip() would also eat a pasted NBSP
_COLUMNS = "id, email, name, role, tz, is_active, token_epoch, password_hash, last_login_at, created_at"


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


def _is_bcrypt(stored: str | None) -> bool:
    return bool(stored) and stored.startswith(("$2a$", "$2b$", "$2y$"))


def verify_password(plain: str, stored: str | None) -> bool:
    """Fails closed on anything that is not a bcrypt hash; no plaintext comparison anywhere."""
    if not _is_bcrypt(stored):
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


def _over_limit_in(conn: db.Conn, key: str, limit: int, window: int) -> bool:
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
        account = _over_limit_in(conn, f"acct:{normalize_email(email)}", *ACCOUNT_LIMIT)
        address = _over_limit_in(conn, f"ip:{ip}", *IP_LIMIT)
    if account or address:
        raise RateLimited()
    user = get_user_by_email(email)
    if not user or not user["is_active"] or user["role"] == "system" or not _is_bcrypt(user["password_hash"]):
        spend_dummy_verify()
        raise InvalidCredentials()
    if not verify_password(password, user["password_hash"]):
        raise InvalidCredentials()
    with db.transaction() as conn:
        conn.execute("UPDATE core_users SET last_login_at = ? WHERE id = ?", (clock.now_iso(), user["id"]))
    return user


def bump_token_epoch_in(conn: db.Conn, user_id: int) -> int:
    """End every session this user holds. Returns the new epoch."""
    row = conn.execute(
        "UPDATE core_users SET token_epoch = token_epoch + 1, updated_at = ? WHERE id = ? RETURNING token_epoch",
        (clock.now_iso(), user_id),
    ).fetchone()
    return int(row[0]) if row else 0


def prune_login_attempts(cancel=None) -> None:
    """Job core.login_attempts_prune: attempts older than a day count toward nothing."""
    with db.transaction() as conn:
        conn.execute("DELETE FROM core_login_attempts WHERE at < ?", (clock.ago(86400),))
