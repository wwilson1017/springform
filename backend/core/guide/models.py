"""Response models for the Guide routes; `app` is "core" or the owning app's slug."""

from backend.core.platform.models import Out


class GuideTopic(Out):
    slug: str
    title: str
    summary: str
    app: str


class GuideHit(Out):
    slug: str
    title: str
    snippet: str
    app: str


class GuideTopicBody(Out):
    slug: str
    title: str
    summary: str
    body_markdown: str
    app: str
