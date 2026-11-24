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

from backend.core import db as core_db, skills
from backend.core.agent import deferred, registry as tool_registry
from backend.core.agent.assembly import CHARS_PER_TOKEN
from backend.core.agent.deferred import BUDGET_TOKENS
from backend.core.agent.engine import chat_tools
from backend.core.agent.providers import fake
from backend.core.agent.spec import ToolSpec
from backend.core.memory.context_files import DEFAULTS, SOUL


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
        specs = chat_tools(a.principal)  # while the app is up: some tools read a setting to decide
    assert r.status_code == 200, r.text
    static, tools = model_requests[0]["system"][0], model_requests[0]["tools"]
    assert DEFAULTS[SOUL].splitlines()[2] in static, "seeded soul.md missing from the measured prompt"
    if path := os.environ.get("PROMPT_REPORT"):
        with open(path, "a") as f:
            f.write(report(static, tools, specs))
    assert len(tools) > 10, "the measured turn offered almost no tools"
    total = tokens(static, tools)
    assert total <= BUDGET_TOKENS, f"static prompt + eager tools ~{total:,} tokens, over the {BUDGET_TOKENS:,} budget"


def test_a_full_skills_index_stays_under_the_budget(login_as, model_requests):
    a = login_as("admin")
    with core_db.transaction() as conn:  # the most the index lists, each at its longest
        for i in range(skills.INDEX_LIMIT):
            name, description = f"{i:02d}-" + "s" * 45, "d" * skills.MAX_DESCRIPTION
            skills.create_in(conn, name, description, "Body.", author="agent", status="active")
    with a:
        assert a.post("/api/agent/chat", json={"message": "hi"}).status_code == 200
    static, tools = model_requests[0]["system"][0], model_requests[0]["tools"]
    assert static.count("d" * skills.MAX_DESCRIPTION) == skills.INDEX_LIMIT
    total = tokens(static, tools)
    assert total <= BUDGET_TOKENS, f"with a full skills index ~{total:,} tokens, over the {BUDGET_TOKENS:,} budget"


def test_the_budget_check_flags_only_an_oversized_prompt():
    tool = [{"name": "core_t", "description": "A tool.", "input_schema": {"type": "object"}}]
    assert tokens("x" * CHARS_PER_TOKEN * (BUDGET_TOKENS + 1), tool) > BUDGET_TOKENS
    assert tokens("x" * CHARS_PER_TOKEN * 100, tool) <= BUDGET_TOKENS


def app_tools(count: int, description: str) -> list[ToolSpec]:
    schema = {"type": "object", "properties": {}}
    return [
        ToolSpec(f"bakery_t{i}", description, schema, writes=False, handler=lambda u, a: None, app="bakery")
        for i in range(count)
    ]


def test_app_tools_are_deferred_by_size_not_only_by_count():
    core = ToolSpec("core_x", "core", {"type": "object"}, writes=False, handler=lambda u, a: None)
    big = [core, *app_tools(5, "d" * (CHARS_PER_TOKEN * BUDGET_TOKENS // 4))]  # 6 tools, over the budget
    active, rest, catalog = deferred.split(big, {"bakery": "Bakery"})
    assert active == [core] and rest == big[1:]
    assert "**Bakery** (bakery): bakery_t0, bakery_t1" in catalog
    small = [core, *app_tools(5, "A tool.")]
    assert deferred.split(small, {"bakery": "Bakery"}) == (small, [], "")
    # the rest of the prompt counts: the same small set is deferred once the prompt fills the budget
    assert deferred.split(small, {}, CHARS_PER_TOKEN * BUDGET_TOKENS)[1] == small[1:]
    assert deferred.split([core], {}, CHARS_PER_TOKEN * BUDGET_TOKENS * 2) == ([core], [], "")  # nothing to defer


def test_a_fork_with_extra_apps_stays_under_the_budget(login_as, model_requests):
    a = login_as("admin")
    before = tool_registry.current()
    extra = app_tools(15, "d" * 1200)  # about 4,600 tokens: under 100 tools, over the budget
    try:
        with a:
            tool_registry.set_current(tool_registry.build_registry([*before.all(), *extra]))
            assert a.post("/api/agent/chat", json={"message": "hi"}).status_code == 200
    finally:
        tool_registry.set_current(before)
    static, tools = model_requests[0]["system"][0], model_requests[0]["tools"]
    names = {t["name"] for t in tools}
    assert len(before.all()) + len(extra) <= deferred.THRESHOLD, "the fixture must stay under the tool-count threshold"
    assert deferred.FIND_TOOLS in names and not any(n.startswith("bakery_") for n in names)
    assert "bakery_t0" in static and all(n.startswith("core_") for n in names)
    total = tokens(static, tools)
    assert total <= BUDGET_TOKENS, f"with extra apps deferred ~{total:,} tokens, over the {BUDGET_TOKENS:,} budget"
