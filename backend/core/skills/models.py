"""Response models for skills (Settings → AI → Skills)."""

from typing import Literal

from backend.core.platform.models import Out


class Skill(Out):
    id: int
    name: str
    description: str
    body: str
    status: Literal["proposed", "active", "archived", "rejected"]
    author: str  # 'agent' (the review) or a user id
    author_name: str | None
    pinned: bool
    use_count: int
    last_used_at: str | None
    source_conversation_id: int | None
    revises_id: int | None
    revises_name: str | None
    created_at: str
    updated_at: str
    approved_at: str | None
    approved_by: int | None


class SkillReview(Out):
    ran_at: str
    status: str  # ok | nothing_to_read | bad_reply | discarded | error
    proposals: int


class SkillsPage(Out):
    """One status's skills, a page at a time; `last_review` is the newest review's ledger row."""

    skills: list[Skill]
    total: int
    last_review: SkillReview | None
