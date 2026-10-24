from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.auth.deps import User, current_user
from backend.core.notifications import push, service

router = APIRouter(prefix="/api/core/notifications", tags=["core"])


class Notification(BaseModel):
    id: int
    title: str
    message: str
    entity_type: str | None
    entity_id: int | None
    link: str | None
    created_at: str
    read_at: str | None


class PushKeys(BaseModel):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class SubscribeIn(BaseModel):
    endpoint: str = Field(max_length=push.ENDPOINT_MAX)
    keys: PushKeys


class UnsubscribeIn(BaseModel):
    endpoint: str = Field(max_length=push.ENDPOINT_MAX)


@router.get("", response_model=list[Notification])
def list_notifications(unread: bool = False, limit: int | None = None, user: User = Depends(current_user)) -> list[dict]:
    """The caller's notifications, newest first; rows whose record they can no longer read are hidden."""
    return service.list_for(user, unread=unread, limit=limit)


@router.get("/unread-count")
def notifications_unread_count(user: User = Depends(current_user)) -> dict:
    return {"count": service.unread_count(user)}


@router.post("/read-all")
def read_all_notifications(user: User = Depends(current_user)) -> dict:
    return {"updated": service.mark_all_read(user)}


@router.post("/{notification_id}/read", response_model=Notification)
def read_notification(notification_id: int, user: User = Depends(current_user)) -> dict:
    return service.mark_read(user, notification_id)


@router.get("/push/public-key")
def push_public_key(user: User = Depends(current_user)) -> dict:
    """The VAPID public key for `pushManager.subscribe({applicationServerKey})`."""
    try:
        return {"public_key": push.vapid_keys()[0]}
    except RuntimeError:
        raise HTTPException(503, detail="push_unavailable") from None


@router.post("/push/subscribe")
def push_subscribe(body: SubscribeIn, user: User = Depends(current_user)) -> dict:
    push.subscribe(user, body.endpoint, body.keys.p256dh, body.keys.auth)
    return {"ok": True}


@router.delete("/push/subscribe")
def push_unsubscribe(body: UnsubscribeIn, user: User = Depends(current_user)) -> dict:
    return {"removed": push.unsubscribe(user, body.endpoint)}
