"""Provider errors by class (agent.md §5, "Provider errors and fallback")."""

import asyncio
import json
from types import SimpleNamespace
from typing import cast

import pytest

from backend.core import db as core_db
from backend.core.agent import errors, history, registry as tool_registry
from backend.core.agent.providers import credentials, fake
from backend.core.agent.providers.fake import FakeProvider
from backend.core.agent.spec import ROUTINE, ToolSpec
from backend.core.agent.turn_hooks import Fail, ProviderFailure, Retry, TurnState

OVERLOADED = {"error": "AI service error (fake-default): overloaded", "status": 529, "code": "overloaded_error"}


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


def of(evs, kind) -> list[dict]:
    return [e for e in evs if e["type"] == kind]


def failure(message="boom", status=None, code=None, retry_after=None) -> ProviderFailure:
    return ProviderFailure(message, 1, status, retry_after, code)


@pytest.mark.parametrize(
    "err,kind",
    [
        (failure(status=401), "auth"),
        (failure(status=403, code="permission_error"), "auth"),
        (failure(status=402), "billing"),
        (failure(status=429, code="insufficient_quota"), "billing"),
        (failure("Your credit balance is too low", status=400), "billing"),
        (failure(status=429), "rate_limit"),
        (failure(status=200, code="rate_limit_error"), "rate_limit"),
        (failure("Request too large: too many tokens per minute", status=429), "rate_limit"),
        (failure(status=413), "context_overflow"),
        (failure(code="context_length_exceeded", status=400), "context_overflow"),
        (failure("prompt is too long: 210000 tokens > 200000 maximum", status=400), "context_overflow"),
        (failure(status=500), "overloaded"),
        (failure(status=529), "overloaded"),
        (failure(status=200, code="overloaded_error"), "overloaded"),
        (failure(code="connection_error"), "overloaded"),
        (failure(status=404, code="not_found_error"), "model_not_found"),
        (failure(code="content_filter", status=400), "policy"),
        (failure("something odd"), "other"),
    ],
)
def test_classify(err, kind):
    assert errors.classify(err) == kind


def _state() -> TurnState:
    return cast(TurnState, SimpleNamespace(scratch={}, provider=FakeProvider("fake-default")))


@pytest.mark.parametrize("retry_after,delay", [(3, 3), (None, 2.0), (120, 10.0), (-2, 0.0)])
def test_rate_limit_retry_delay(retry_after, delay):
    state = _state()

    def ask(err):
        return asyncio.run(errors.on_provider_error(state, err))

    assert ask(failure(status=429, retry_after=retry_after)) == Retry(delay)
    assert ask(failure(status=429)) == Fail("fake-default is rate-limited right now. Try again in a minute.")


def test_rate_limit_retries_once_then_names_the_model(login_as):
    a = login_as("member")
    fake.script({"error": "slow down", "status": 429, "retry_after": 0}, "fine")
    evs = chat(a, message="hi")
    assert evs[-1]["type"] == "done" and of(evs, "text")[-1]["text"] == "fine"
    fake.script({"error": "slow down", "status": 429, "retry_after": 0}, {"error": "slow down", "status": 429})
    assert chat(a, message="hi")[-1]["error"] == "fake-default is rate-limited right now. Try again in a minute."


@pytest.fixture
def counter(app):
    """A read tool that counts its runs and answers 1,000 characters."""
    before, runs = tool_registry.current(), []
    spec = ToolSpec(
        name="core_count_page",
        description="A page.",
        input_schema={"type": "object", "properties": {}},
        writes=False,
        handler=lambda u, a: runs.append(1) or "z" * 1000,
    )
    tool_registry.set_current(tool_registry.build_registry([*before.all(), spec]))
    yield runs
    tool_registry.set_current(before)


def test_context_overflow_clears_and_repeats_the_call_without_rerunning_tools(login_as, counter):
    a = login_as("member")
    fake.script(*[{"tool": "core_count_page", "args": {"n": i}} for i in range(4)])
    fake.script({"error": "prompt is too long", "status": 400}, "ok")
    evs = chat(a, message="read")
    assert evs[-1]["type"] == "done" and of(evs, "text")[-1]["text"] == "ok" and len(counter) == 4
    fake.script({"error": "prompt is too long", "status": 400})  # nothing left to clear
    assert (
        chat(a, message="hi")[-1]["error"]
        == "This conversation is too long for fake-default. Start a new conversation."
    )


def test_overload_falls_back_for_this_turn_only(login_as):
    a = login_as("member")
    fake.script(OVERLOADED, "from the light model")
    evs = chat(a, message="hi")
    assert (evs[-1]["type"], evs[-1]["model"]) == ("done", "fake-light")
    cid = evs[0]["id"]
    assert chat(a, conversation_id=cid, message="again")[-1]["model"] == "fake-default"


@pytest.fixture
def send_tool(app):
    before = tool_registry.current()
    sent = []
    note = ToolSpec(
        name="core_note_thing",
        description="Note a thing.",
        input_schema={"type": "object", "properties": {}},
        writes=True,
        confirm_tier=ROUTINE,
        targets=lambda a: [],
        handler_in=lambda conn, u, a: {"noted": True},
    )
    spec = ToolSpec(
        name="core_send_thing",
        description="Send a thing out.",
        input_schema={"type": "object", "properties": {}},
        writes=True,
        external_effect=True,
        handler=lambda u, a: sent.append(1) or {"sent": True},
    )
    tool_registry.set_current(tool_registry.build_registry([*before.all(), spec, note]))
    yield sent
    tool_registry.set_current(before)


def test_a_fallback_never_happens_after_a_write_ran(login_as, send_tool):
    a = login_as("member")
    # a routine write earlier in the same turn
    fake.script({"tool": "core_note_thing"}, OVERLOADED, "from the light model")
    evs = chat(a, message="make one")
    assert of(evs, "tool_end")[0]["status"] == "done"
    assert evs[-1]["error"] == "fake-default is overloaded or unreachable right now. Try again in a minute."
    assert fake._script[0] == "from the light model"  # the fallback model was never called
    fake.reset()

    # an approved external effect, then the continuation's first call fails
    fake.script({"tool": "core_send_thing"}, "Sending needs your approval.")
    evs = chat(a, message="send it")
    confirm, cid = of(evs, "confirm")[0], evs[0]["id"]
    assert (
        a.post("/api/agent/confirm", json={"tool_run_id": confirm["tool_run_id"], "decision": "approve"}).json()[
            "status"
        ]
        == "done"
    )
    fake.script(OVERLOADED, "from the light model")
    evs = chat(a, conversation_id=cid)
    assert evs[-1]["type"] == "error" and "fake-default is overloaded" in evs[-1]["error"] and send_tool == [1]
    fake.reset()

    # only a read ran: the fallback is fine
    fake.script({"tool": "example_list_widgets", "args": {}}, OVERLOADED, "from the light model")
    evs = chat(a, message="list")
    assert (evs[-1]["type"], evs[-1]["model"]) == ("done", "fake-light")


def test_wrote_ignores_reads_refusals_and_find_tools(login_as, send_tool):
    a = login_as("member")
    cid = chat(a, message="hi")[0]["id"]
    mid = history.save_message(cid, "assistant", {"text": "x"})
    by_name = {s.name: s for s in tool_registry.current().all()}
    state = cast(TurnState, SimpleNamespace(conversation_id=cid, by_name=by_name))
    for tool, status in [
        ("example_list_widgets", "done"),
        ("core_note_thing", "error"),
        ("core_note_thing", "pending"),
        ("core_find_tools", "done"),
    ]:
        history.insert_tool_run(
            tool=tool, args={}, status=status, user_id=a.principal.id, conversation_id=cid, message_id=mid
        )
    assert errors._wrote(state) is False
    old = history.insert_tool_run(
        tool="core_note_thing", args={}, status="executing", user_id=a.principal.id, conversation_id=cid
    )
    assert errors._wrote(state) is True  # an approval still running, whatever message it came from
    history.resolve(old, "done", expect="executing")
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_agent_tool_runs SET resolved_at = '2000-01-01T00:00:00Z' WHERE id = ?", (old,))
    assert errors._wrote(state) is False
    history.insert_tool_run(
        tool="gone_tool", args={}, status="done", user_id=a.principal.id, conversation_id=cid, message_id=mid
    )
    assert errors._wrote(state) is True


def test_no_alternative_fails_naming_the_model(login_as):
    admin = login_as("admin")
    admin.get("/api/agent/agents")
    assert admin.patch("/api/agent/agents/whisk", json={"model_tier": "light"}).status_code == 200
    fake.script(OVERLOADED)
    assert (
        chat(admin, message="hi")[-1]["error"]
        == "fake-light is overloaded or unreachable right now. Try again in a minute."
    )


def test_alternative_prefers_the_other_vendor_then_the_light_tier(db, monkeypatch):
    monkeypatch.delenv("AGENT_FAKE_PROVIDER")
    credentials.update("anthropic", api_key="k1", model_default="claude-a", model_light="claude-b", enabled=True)
    anthropic = errors.providers.get_provider()
    assert anthropic is not None and anthropic.provider_name == "anthropic"
    assert errors._alternative(anthropic).model == "claude-b"  # one vendor: its light model
    light = errors.providers.get_provider(tier="light")
    assert light is not None
    assert errors._alternative(light) is None  # already on the light model
    credentials.update("openai", api_key="k2", model_default="gpt-a", model_light="gpt-b", enabled=True)
    other = errors._alternative(anthropic)
    assert (other.provider_name, other.model) == ("openai", "gpt-a")


def test_no_fallback_after_an_older_card_is_approved_or_an_effect_is_uncertain(login_as, send_tool, app):
    a = login_as("member")
    fake.script({"tool": "core_send_thing"}, "Sending needs your approval.")
    evs = chat(a, message="send it")
    confirm, cid = of(evs, "confirm")[0], evs[0]["id"]
    chat(a, conversation_id=cid, message="something else meanwhile")  # a newer user message
    a.post("/api/agent/confirm", json={"tool_run_id": confirm["tool_run_id"], "decision": "approve"})
    fake.script(OVERLOADED, "from the light model")
    assert "fake-default is overloaded" in chat(a, conversation_id=cid)[-1]["error"]
    fake.reset()

    before = tool_registry.current()

    def fails(user, args):
        raise RuntimeError("the remote end hung up")

    flaky = ToolSpec(
        name="core_post_thing",
        description="Post a thing.",
        input_schema={"type": "object", "properties": {}},
        writes=True,
        external_effect=True,
        handler=fails,
    )
    tool_registry.set_current(tool_registry.build_registry([*before.all(), flaky]))
    fake.script({"tool": "core_post_thing"}, "Needs approval.")
    evs = chat(a, message="post it")
    confirm, cid = of(evs, "confirm")[0], evs[0]["id"]
    r = a.post("/api/agent/confirm", json={"tool_run_id": confirm["tool_run_id"], "decision": "approve"}).json()
    assert r["status"] == "uncertain"
    fake.script(OVERLOADED, "from the light model")
    assert "fake-default is overloaded" in chat(a, conversation_id=cid)[-1]["error"]


def test_the_last_answer_survives_a_fallback(login_as, monkeypatch):
    from backend.core.agent import turn_hooks, turns

    monkeypatch.setattr(turns, "MAX_ITERATIONS", 1)
    sent = []
    point = turn_hooks.REGISTERED["before_model_call"]
    monkeypatch.setitem(
        turn_hooks.REGISTERED, "before_model_call", [*point, lambda s: sent.append(json.dumps(s.messages))]
    )
    fake.script({"tool": "example_list_widgets", "args": {}}, OVERLOADED, "Here is what I have.")
    evs = chat(login_as("member"), message="dig")
    assert evs[-1]["model"] == "fake-light" and turns.LAST_ANSWER in sent[-1]
    assert "Here is what I have." in [e["text"] for e in of(evs, "text")]


def test_a_refusal_is_an_error_for_one_shot_calls():
    from backend.core.agent.providers import ProviderError, collect_text

    async def stream():
        yield {"type": "text", "text": "I won't"}
        yield {"type": "_turn_complete", "tool_calls": [], "stop_reason": "refusal"}

    with pytest.raises(ProviderError):
        asyncio.run(collect_text(stream()))
