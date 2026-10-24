"""Web Push: VAPID keys, browser subscriptions, and the `push` delivery channel.

The keypair is generated once, on first use, and kept in core_settings (the private key
encrypted). Regenerating it would orphan every subscription, so a stored private key that no
longer decrypts (ENCRYPTION_KEY changed) is an error, never a silent rotation.

A subscription row is a browser; subscribing again re-stamps it to whoever is signed in there.
A push service answering 404/410 marks the subscription `failed_at`; it receives nothing more
until the browser subscribes again. pywebpush is imported lazily (tests replace it).
"""

from __future__ import annotations

import base64
import ipaddress
import json
from urllib.parse import urlparse

from backend.core import clock, db, settings
from backend.core.auth.deps import User
from backend.core.errors import Invalid
from backend.core.notifications.service import Undeliverable, register_channel

PUBLIC_KEY = "notifications.vapid_public_key"
PRIVATE_KEY = "notifications.vapid_private_key"
PAYLOAD_MAX_BYTES = 3900  # under the 4 KB Web Push limit
TIMEOUT = 10  # seconds per push service request
TTL = 86400  # the push service keeps an undelivered message a day (0 would drop it when offline)
ENDPOINT_MAX = 2000


def _generate_keypair() -> tuple[str, str]:
    """(public, private) b64url: the uncompressed P-256 point the browser's applicationServerKey
    wants, and the raw 32-byte private value pywebpush signs with."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    key = ec.generate_private_key(ec.SECP256R1())
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    public = key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return b64(public), b64(key.private_numbers().private_value.to_bytes(32, "big"))


def vapid_keys() -> tuple[str, str]:
    """(public, private), generated and stored on first use. Never call inside a transaction."""
    if settings.get_setting(PUBLIC_KEY) is None:
        with db.transaction() as conn:
            if conn.execute("SELECT 1 FROM core_settings WHERE key = ?", (PUBLIC_KEY,)).fetchone() is None:
                public, private = _generate_keypair()
                settings.set_setting_in(conn, PUBLIC_KEY, public, None)
                settings.set_setting_in(conn, PRIVATE_KEY, private, None, is_secret=True)
    public, private = settings.get_setting(PUBLIC_KEY), settings.get_setting(PRIVATE_KEY)
    if not private:
        raise RuntimeError(
            "The stored VAPID private key cannot be decrypted (did ENCRYPTION_KEY change?). "
            "Restore the original ENCRYPTION_KEY; web push stays off until then."
        )
    return public, private


def subject() -> str:
    """The VAPID `sub` claim: the install's https URL, else a mailto placeholder (push services
    accept only those two forms)."""
    url = settings.public_url()
    return url if url.startswith("https://") else "mailto:push@springform.invalid"


def is_safe_endpoint(endpoint: str) -> bool:
    """An https URL of bounded length whose host is not obviously internal. Defense in depth
    against SSRF (the server POSTs to it); DNS is not resolved."""
    if not endpoint or len(endpoint) > ENDPOINT_MAX:
        return False
    try:
        parsed = urlparse(endpoint)
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in ("localhost", "localhost.localdomain") or host.endswith(".localhost"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True  # a hostname, not an IP literal
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def subscribe_in(conn: db.Conn, user: User, endpoint: str, p256dh: str, auth: str) -> None:
    if not is_safe_endpoint(endpoint):
        raise Invalid("endpoint must be a public https push service URL")
    if not p256dh or not auth:
        raise Invalid("keys.p256dh and keys.auth are required")
    conn.execute(
        """INSERT INTO core_push_subscriptions (user_id, endpoint, p256dh, auth, created_at) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (endpoint) DO UPDATE SET user_id = excluded.user_id, p256dh = excluded.p256dh,
                                                auth = excluded.auth, failed_at = NULL""",
        (user.id, endpoint, p256dh, auth, clock.now_iso()),
    )


def subscribe(user: User, endpoint: str, p256dh: str, auth: str) -> None:
    with db.transaction() as conn:
        subscribe_in(conn, user, endpoint, p256dh, auth)


def unsubscribe_in(conn: db.Conn, user: User, endpoint: str) -> bool:
    """Only the caller's own subscription; another user's endpoint reports False, not 403."""
    return conn.execute("DELETE FROM core_push_subscriptions WHERE endpoint = ? AND user_id = ?", (endpoint, user.id)).rowcount > 0


def unsubscribe(user: User, endpoint: str) -> bool:
    with db.transaction() as conn:
        return unsubscribe_in(conn, user, endpoint)


def has_subscription_in(conn: db.Conn, user_id: int) -> bool:
    sql = "SELECT 1 FROM core_push_subscriptions WHERE user_id = ? AND failed_at IS NULL"
    return conn.execute(sql, (user_id,)).fetchone() is not None


def _payload(p: dict) -> str:
    body = p["message"] or p["title"]
    data = {"notification_id": p["notification_id"], "title": p["title"], "body": body, "url": p["link"] or "/"}
    if len(json.dumps(data).encode()) > PAYLOAD_MAX_BYTES:
        data["body"] = body[:400]
    return json.dumps(data)


def send(p: dict) -> None:
    """The push channel: every live subscription of the recipient. Raises (retry) when any push
    service failed for another reason than a dead subscription; a device that already got it
    may then get it again, and drops it by notification_id."""
    subs = db.rows(
        "SELECT id, endpoint, p256dh, auth FROM core_push_subscriptions WHERE user_id = ? AND failed_at IS NULL ORDER BY id",
        (p["user_id"],),
    )
    if not subs:
        raise Undeliverable("no live push subscription")
    from pywebpush import WebPushException, webpush

    _, private = vapid_keys()
    data, dead, errors = _payload(p), [], []
    for sub in subs:
        try:
            webpush(
                subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                data=data, vapid_private_key=private, vapid_claims={"sub": subject()}, timeout=TIMEOUT, ttl=TTL,
            )
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):
                dead.append(sub["id"])
            else:
                errors.append(f"{status}: {e}")
        except Exception as e:
            errors.append(repr(e))
    if dead:
        with db.transaction() as conn:
            conn.execute(
                "UPDATE core_push_subscriptions SET failed_at = ? WHERE id IN (SELECT value FROM json_each(?))",
                (clock.now_iso(), json.dumps(dead)),
            )
    if errors:
        raise RuntimeError("; ".join(errors)[:2000])
    if len(dead) == len(subs):
        raise Undeliverable("every push subscription is gone")


register_channel("push", send, enabled_in=has_subscription_in)
