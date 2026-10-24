"""REST for business memory (facts) and context files. Members read; admins see provenance,
forget facts and edit unprotected context files. Protected files are refused here (403
`protected_file`): they change only through the confirmed chat tool."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.core.auth.deps import User, current_user, require_admin
from backend.core.memory import context_files, facts

router = APIRouter(tags=["core"])


class FactIn(BaseModel):
    text: str
    tags: list[str] = []
    valid_from: str | None = None


class ContextFileIn(BaseModel):
    content: str


def _view(user: User):
    return facts.with_provenance if user.is_admin else facts.public


@router.get("/api/core/memory/facts")
def list_memory_facts(
    q: str | None = None, limit: int = 50, offset: int = 0, history: bool = False, user: User = Depends(current_user)
) -> list[dict]:
    """Current facts (search when `q` is given). `history` (admins only) adds ended facts after them."""
    history = history and user.is_admin
    found = (
        facts.search(q, limit, include_history=history)
        if q
        else facts.list_facts(limit, offset, include_history=history)
    )
    return [_view(user)(f) for f in found]


@router.post("/api/core/memory/facts")
def add_memory_fact(body: FactIn, user: User = Depends(current_user)) -> dict:
    fact = facts.remember(body.text, author_user_id=user.id, valid_from=body.valid_from, tags=body.tags)
    return _view(user)(fact)


@router.delete("/api/core/memory/facts/{fact_id}")
def forget_memory_fact(fact_id: int, user: User = Depends(require_admin)) -> dict:
    return facts.with_provenance(facts.forget(fact_id, user.id))


@router.get("/api/core/context-files")
def list_context_files(agent: str = context_files.DEFAULT_AGENT, user: User = Depends(current_user)) -> list[dict]:
    return context_files.list_files(agent, user)


@router.get("/api/core/context-files/{filename}")
def read_context_file(filename: str, agent: str = context_files.DEFAULT_AGENT, user: User = Depends(current_user)) -> dict:
    return context_files.read(agent, filename, user)


@router.put("/api/core/context-files/{filename}")
def write_context_file(
    filename: str, body: ContextFileIn, agent: str = context_files.DEFAULT_AGENT, user: User = Depends(require_admin)
) -> dict:
    return context_files.write(agent, filename, body.content, user)
