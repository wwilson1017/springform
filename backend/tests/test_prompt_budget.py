"""The prompt budget: what every turn sends before the conversation (the static half of the system
prompt plus the tool definitions sent eagerly) stays under BUDGET_TOKENS, estimated as characters / 4.

Measured on an admin's first turn of a fresh install (admins see every tool), with the lifespan run so
the seeded soul.md is in the prompt. With PROMPT_REPORT set to a file path the test appends a Markdown
report of the sizes and the chat tool surface; CI points it at the job summary so a PR shows what it
changed. Raise the budget only on purpose, in the PR that needs it.
"""

import json
import os

import pytest

from backend.core.agent.assembly import CHARS_PER_TOKEN
from backend.core.agent.engine import chat_tools
from backend.core.agent.providers import fake
from backend.core.memory.context_files import DEFAULTS, SOUL

BUDGET_TOKENS = 14_000


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    fake.reset()
    yield
    fake.reset()


def tokens(static: str, tools: list[dict]) -> int:
    return (len(static) + len(json.dumps(tools))) // CHARS_PER_TOKEN


def report(static: str, tools: list[dict], specs) -> str:
    eager = {t["name"] for t in tools}
    p, t = len(static) // CHARS_PER_TOKEN, len(json.dumps(tools)) // CHARS_PER_TOKEN
    lines = [
        "## Whisk prompt size",
        "",
        "| Part | Tokens (chars / 4) |",
        "|---|---|",
        f"| Static system prompt | {p:,} |",
        f"| Eager tool definitions ({len(tools)}) | {t:,} |",
        f"| **Total** (budget {BUDGET_TOKENS:,}) | **{p + t:,}** |",
        "",
        f"### Chat tool surface ({len(specs)} tools)",
        "",
        "| Tool | writes | always_confirm | confirm_tier | eager |",
        "|---|---|---|---|---|",
    ]
    for s in sorted(specs, key=lambda s: s.name):
        lines.append(f"| `{s.name}` | {s.writes} | {s.always_confirm} | {s.confirm_tier or ''} | {s.name in eager} |")
    return "\n".join(lines) + "\n"


def test_static_prompt_and_eager_tools_stay_under_the_budget(login_as, model_requests):
    a = login_as("admin")
    with a:  # run the lifespan: startup seeds soul.md into the static prompt
        r = a.post("/api/agent/chat", json={"message": "hi"})
    assert r.status_code == 200, r.text
    static, tools = model_requests[0]["system"][0], model_requests[0]["tools"]
    assert DEFAULTS[SOUL].splitlines()[2] in static, "seeded soul.md missing from the measured prompt"
    if path := os.environ.get("PROMPT_REPORT"):
        with open(path, "a") as f:
            f.write(report(static, tools, chat_tools(a.principal)))
    assert len(tools) > 10, "the measured turn offered almost no tools"
    total = tokens(static, tools)
    assert total <= BUDGET_TOKENS, f"static prompt + eager tools ~{total:,} tokens, over the {BUDGET_TOKENS:,} budget"


def test_the_budget_check_flags_only_an_oversized_prompt():
    tool = [{"name": "core_t", "description": "A tool.", "input_schema": {"type": "object"}}]
    assert tokens("x" * CHARS_PER_TOKEN * (BUDGET_TOKENS + 1), tool) > BUDGET_TOKENS
    assert tokens("x" * CHARS_PER_TOKEN * 100, tool) <= BUDGET_TOKENS
