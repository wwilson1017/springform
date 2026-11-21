"""Admin routes for skills, under /api/core/skills: list a status, write one by hand (active at
once), edit, and approve, reject, archive or restore. Nothing deletes a skill."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from backend.core import db, skills
from backend.core.auth.deps import User, require_admin
from backend.core.skills import models

router = APIRouter(prefix="/api/core/skills", tags=["core"], dependencies=[Depends(require_admin)])


class SkillIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str
    body: str


class SkillPatch(BaseModel):
    """Omitted fields stay as they are."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    description: str | None = None
    body: str | None = None
    pinned: bool | None = None


@router.get("", response_model=models.SkillsPage)
def skills_list(
    status: Literal["proposed", "active", "archived", "rejected"] = "active",
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    found, total = skills.list_skills(status, limit, offset)
    last = db.one("SELECT ran_at, status, proposals FROM core_agent_skill_reviews ORDER BY id DESC LIMIT 1")
    return {"skills": found, "total": total, "last_review": last}


@router.post("", response_model=models.Skill)
def skills_create(body: SkillIn, user: User = Depends(require_admin)) -> dict:
    return skills.create(body.name, body.description, body.body, user)


@router.patch("/{skill_id}", response_model=models.Skill)
def skills_update(skill_id: int, body: SkillPatch) -> dict:
    return skills.update(skill_id, {k: v for k, v in body.model_dump().items() if v is not None})


@router.post("/{skill_id}/{action}", response_model=models.Skill)
def skills_move(
    skill_id: int, action: Literal["approve", "reject", "archive", "restore"], user: User = Depends(require_admin)
) -> dict:
    return skills.move(skill_id, action, user)
