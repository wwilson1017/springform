"""Response models for the notification counters and web push. `Notification` itself lives in
router.py with the routes that already used it."""

from backend.core.platform.models import Out


class UnreadCount(Out):
    count: int


class PushPublicKey(Out):
    """The VAPID public key for `pushManager.subscribe({applicationServerKey})`."""

    public_key: str


class PushRemoved(Out):
    removed: bool
