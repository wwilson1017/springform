"""Whisk's request tools: search the Requests board, and file a request as a GitHub issue on this
install's repo (Settings → Integrations → GitHub).

Filing is an outside effect: every call shows the Approve card with the draft, no always-allow
rule skips it, and it is never offered over MCP or to jobs. The server adds the reporter (the
signed-in user), "Via" (the default agent's current name), the app and the version; the model cannot set them. The tool
is offered only while GitHub is connected, so a member never approves a draft that cannot be sent.
"""

from __future__ import annotations

from backend.core.agent import agents
from backend.core.agent.spec import ToolSpec
from backend.core.errors import Invalid
from backend.core.requests import github, service
from backend.core.timeline.tools import human

SEARCH, FILE = "core_request_search", "core_request_file"
EXPIRED_HINT = (
    "GitHub refused the token: it may have expired or been revoked. An admin can set a new one in "
    "Settings → Integrations → GitHub."
)

FILE_DESCRIPTION = """\
File a request (a bug or a feature) as an issue on this install's GitHub repo, where its maintainers \
pick it up. The user approves your draft before it is sent.

Before filing:
- Call core_request_search first. If it is already filed, tell the user and link it instead.
- Check whether it already exists (core_code_search, the docs folders). If it does, teach the user \
how to do it (app, screen, clicks) instead of filing.
- Ask until a developer who never saw this chat could build it without asking anything. Ask one or \
two questions at a time. Every decision goes to the user with your own recommendation.
- A bug needs steps to reproduce, what should happen and what happens instead. "It should save" is \
not a bug report until you also know what it does instead.
- A feature needs who it is for, the use case, and the behaviour wanted.
- Questions you cannot settle with the user go in open_questions, not the description.
- Never include passwords, card numbers or private customer details; describe the case instead.
- File once per topic per chat.

Write the description in Markdown with short sections (for a bug: Steps, Expected, Actual; for a \
feature: Use case, Proposed behaviour, Edge cases). Do not add who asked or the version: those are \
added for you."""


def _filing(user) -> bool:
    return human(user) and service.config()["configured"]


def _search(user, args: dict) -> dict:
    state = args.get("state") or "all"
    if state not in ("open", "closed", "all"):
        raise Invalid("state must be open, closed or all")
    rows = service.list_requests(state, limit=20, q=args.get("query"))
    keep = ("issue_number", "url", "state", "title", "app", "created_at")
    return {"requests": [{k: r[k] for k in keep} for r in rows]}


def _file(user, args: dict) -> dict:
    questions = args.get("open_questions") or []
    if not isinstance(questions, list):
        raise Invalid("open_questions must be a list of questions")
    try:
        row = service.create(
            user,
            str(args.get("title") or ""),
            str(args.get("app") or "core"),
            str(args.get("description") or ""),
            kind=str(args.get("kind") or ""),
            open_questions=[str(q) for q in questions],
            via=agents.get()["name"],
        )
    except github.GitHubError as e:
        if " 401" in e.detail:
            raise github.GitHubError(EXPIRED_HINT) from e
        raise
    return {k: row[k] for k in ("issue_number", "url", "title", "app", "labels")}


def get_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name=SEARCH,
            description=(
                "Search the requests filed from this install (the Requests board, mirrored from GitHub) by words "
                "in the title or description. Use it before core_request_file to avoid a duplicate."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Words to look for; empty lists the newest"},
                    "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "all"},
                },
            },
            writes=False,
            handler=_search,
            enabled=human,
        ),
        ToolSpec(
            name=FILE,
            description=FILE_DESCRIPTION,
            input_schema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "maxLength": service.MAX_TITLE,
                        "description": "Short and specific, e.g. 'Show the delivery date on the order list'",
                    },
                    "app": {"type": "string", "description": "The app's slug (crm, todos, …) or 'core'"},
                    "kind": {"type": "string", "enum": ["bug", "feature"]},
                    "description": {"type": "string", "maxLength": service.MAX_DESCRIPTION},
                    "open_questions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Decisions still open for the maintainers; leave empty when none",
                    },
                },
                "required": ["title", "app", "kind", "description"],
            },
            writes=True,
            external_effect=True,
            handler=_file,
            enabled=_filing,
            mcp_exposed=False,
            summary="File this request on GitHub.",
        ),
    ]
