"""core_search_conversations (agent.md §4, "Core tools")."""

import json

import pytest

from backend.core.agent import history, registry as tool_registry, tools
from backend.core.agent.providers import fake


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    fake.reset()
    yield
    fake.reset()


def chat(client, **body) -> list[dict]:
    r = client.post("/api/agent/chat", json=body)
    assert r.status_code == 200, r.text
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


def search(client, **args) -> tuple[dict, int]:
    evs = chat(client, message="/tool core_search_conversations " + json.dumps(args))
    [end] = [e for e in evs if e["type"] == "tool_end"]
    return end["result"], evs[0]["id"]


def test_search_finds_only_the_callers_earlier_conversations(login_as):
    a, b = login_as("member"), login_as("member")
    earlier = chat(a, message="Notes on the zanzibar contract")[0]["id"]
    found, asking = search(a, query="zanzibar")
    assert found["note"] == tools.SEARCH_NOTE
    assert {r["conversation_id"] for r in found["results"]} == {earlier} and asking != earlier
    assert any("zanzibar" in r["snippet"] for r in found["results"])
    assert search(b, query="zanzibar")[0]["results"] == []


def test_private_threads_are_searched_and_punctuation_is_not_syntax(login_as):
    a = login_as("member")
    cid = chat(a, message='quote "kumquat" AND (OR) * now')[0]["id"]
    a.patch(f"/api/agent/conversations/{cid}", json={"is_private": True})
    assert {r["conversation_id"] for r in search(a, query='"kumquat" (OR')[0]["results"]} == {cid}


def test_a_tainted_thread_gives_only_the_users_words(login_as):
    a = login_as("member")
    cid = chat(a, message="about quince")[0]["id"]
    history.mark_tainted(cid)
    assert {r["role"] for r in search(a, query="quince")[0]["results"]} == {"user"}


def test_limit_is_clamped(login_as):
    a = login_as("member")
    for _ in range(3):
        chat(a, message="persimmon")
    assert len(history.search_messages(a.principal.id, "persimmon", exclude=None, limit=0)) == 1
    assert len(history.search_messages(a.principal.id, "persimmon", exclude=None, limit=500)) == 6
    assert history.search_messages(a.principal.id, "  ", exclude=None) == []


def test_search_is_not_offered_over_mcp(app):
    assert "core_search_conversations" not in {s.name for s in tool_registry.current().for_source("mcp")}
