from fastapi import APIRouter, Depends

from backend.core import registry
from backend.core.auth.deps import User, current_user
from backend.core.errors import NotFound
from backend.core.guide import library, models

router = APIRouter(prefix="/api/core/guide", tags=["core"])
MAX_RESULTS = 20


def _readable(user: User) -> list[library.Topic]:
    """Core topics plus those of the apps on the caller's launcher (hidden apps stay hidden from members)."""
    apps = {"core"} | {a["slug"] for a in registry.list_for_user(user)}
    return [t for t in library.topics() if t.app in apps]


@router.get("", response_model=list[models.GuideTopic])
def guide_list(user: User = Depends(current_user)) -> list[dict]:
    return [{"slug": t.slug, "title": t.title, "summary": t.summary, "app": t.app} for t in _readable(user)]


@router.get("/search", response_model=list[models.GuideHit])
def guide_search(q: str = "", limit: int = 10, user: User = Depends(current_user)) -> list[dict]:
    hits = library.search(_readable(user), q, max(1, min(limit, MAX_RESULTS)))
    return [{"slug": t.slug, "title": t.title, "snippet": s, "app": t.app} for t, s in hits]


@router.get("/{slug}", response_model=models.GuideTopicBody)
def guide_topic(slug: str, user: User = Depends(current_user)) -> dict:
    for t in _readable(user):
        if t.slug == slug:
            return {"slug": t.slug, "title": t.title, "summary": t.summary, "body_markdown": t.body, "app": t.app}
    raise NotFound("no such topic")
