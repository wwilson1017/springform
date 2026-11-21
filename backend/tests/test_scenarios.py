"""Whisk scenarios: each `scenarios/*.yaml` scripts the FakeProvider, drives real turns over HTTP
(the server-owned turn in `detached.py` running `turns.TurnRunner`), and checks the events each step
emits and what the model was sent. The file format is in docs/agents/testing.md ("Whisk scenarios").

The client runs the app's lifespan (`with TestClient(app)`), so every request shares one event loop
and leaving a stream early is a real disconnect.
"""

import json
import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.core.agent import delimiters, registry as tool_registry
from backend.core.agent.providers import fake
from backend.core.agent.spec import ToolSpec

SCENARIOS = Path(__file__).parent / "scenarios"
TOP_KEYS = {"name", "role", "context_window", "tools", "steps"}
FLAGS = ("confirm_tier", "always_confirm", "untrusted_source", "external_effect")
TOOL_KEYS = {"name", "description", "writes", "returns", *FLAGS}
ACTIONS = {"send", "continue", "approve", "deny", "resume"}
STEP_KEYS = ACTIONS | {"replies", "drop_after", "events", "request", "status"}
REQUEST_KEYS = {"call", "messages_contain", "messages_exclude", "messages_match", "system_contains"}
TERMINAL = {"done", "error"}


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    fake.reset()
    yield
    fake.reset()


def _strict(where: str, obj: dict, allowed: set[str]) -> None:
    assert isinstance(obj, dict), f"{where}: expected a mapping, got {obj!r}"
    unknown = set(obj) - allowed
    assert not unknown, f"{where}: unknown keys {sorted(unknown)} (allowed: {sorted(allowed)})"


def load(path: Path) -> dict:
    spec = yaml.safe_load(path.read_text())
    _strict(path.name, spec, TOP_KEYS)
    assert spec.get("name") and spec.get("steps"), f"{path.name}: needs a name and steps"
    for i, step in enumerate(spec["steps"], 1):
        _strict(f"{path.name} step {i}", step, STEP_KEYS)
        assert len(ACTIONS & set(step)) == 1, f"{path.name} step {i}: exactly one of {sorted(ACTIONS)}"
        for req in _listed(step.get("request")):
            _strict(f"{path.name} step {i} request", req, REQUEST_KEYS)
    for tool in spec.get("tools", []):
        _strict(f"{path.name} tool", tool, TOOL_KEYS)
    return spec


def _listed(value) -> list:
    return [] if value is None else value if isinstance(value, list) else [value]


def tool_spec(t: dict) -> ToolSpec:
    """A test-only core tool: a read, a local write (`handler_in`, no targets) or an external-effect
    write (`handler`), answering `returns` (default `{ok: true}`)."""
    returns = t.get("returns", {"ok": True})
    writes = t.get("writes", False)
    local_write = writes and not t.get("external_effect")
    flags = {k: t[k] for k in FLAGS if k in t}
    return ToolSpec(
        name=t["name"],
        description=t.get("description", "A scenario tool."),
        input_schema={"type": "object", "properties": {}},
        writes=writes,
        handler=None if local_write else (lambda user, args: returns),
        handler_in=(lambda conn, user, args: returns) if local_write else None,
        targets=(lambda args: []) if local_write else None,
        **flags,
    )


def _texts(obj) -> str:
    """Every string inside a provider request part, one per line (so fences read as sent)."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return "\n".join(_texts(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return "\n".join(_texts(v) for v in obj)
    return ""


def check_events(evs: list[dict], wanted: list) -> None:
    """`wanted` appears in `evs` in order (other events may sit between); a string is a type, a
    mapping matches the keys it names."""
    it = iter(evs)
    for w in wanted:
        w = {"type": w} if isinstance(w, str) else w
        assert any(all(e.get(k) == v for k, v in w.items()) for e in it), (
            f"no event matching {w} (in order) among {json.dumps(evs, default=str)[:2000]}"
        )


def check_request(calls: list[dict], req: dict) -> None:
    assert calls, "this step made no model call"
    at = req.get("call", -1)
    call = calls[at]
    messages, system = _texts(call["messages"]), _texts(call["system"])
    for text in req.get("messages_contain", []):
        assert text in messages, f"model call {at}: messages lack {text!r}:\n{messages[-3000:]}"
    for text in req.get("messages_exclude", []):
        assert text not in messages, f"model call {at}: messages contain {text!r}"
    for pattern in req.get("messages_match", []):
        assert re.search(pattern, messages), f"model call {at}: messages do not match {pattern!r}:\n{messages[-3000:]}"
    for text in req.get("system_contains", []):
        assert text in system, f"model call {at}: system prompt lacks {text!r}"


def stream(c: TestClient, method: str, url: str, drop_after: str | None = None, **kw) -> list[dict]:
    evs = []
    with c.stream(method, url, **kw) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("data: "):
                evs.append(json.loads(line[6:]))
                if drop_after and evs[-1]["type"] == drop_after:
                    break  # leaving the block disconnects
    return evs


def run(path: Path, app, login_as, model_requests: list[dict], monkeypatch) -> None:
    spec = load(path)
    if "context_window" in spec:
        monkeypatch.setattr(fake, "CONTEXT_WINDOW", spec["context_window"])
    before = tool_registry.current()
    tool_registry.set_current(tool_registry.build_registry([*before.all(), *map(tool_spec, spec.get("tools", []))]))
    who = login_as(spec.get("role", "member"))
    cid = turn_id = None
    last_seq = -1
    seen: list[dict] = []
    try:
        with TestClient(app, headers={"Authorization": f"Bearer {who.cookies.get('sf_session')}"}) as c:
            for i, step in enumerate(spec["steps"], 1):
                try:
                    fake.script(*step.get("replies", []))
                    mark = len(model_requests)
                    evs: list[dict] = []
                    if "send" in step or "continue" in step:
                        body = {"message": step["send"]} if "send" in step else {}
                        evs = stream(
                            c,
                            "POST",
                            "/api/agent/chat",
                            step.get("drop_after"),
                            json={**body, **({"conversation_id": cid} if cid else {})},
                        )
                        assert evs and evs[0]["type"] == "conversation_id", evs
                        cid, turn_id, first = evs[0]["id"], evs[0]["turn_id"], 0
                    elif "resume" in step:
                        assert turn_id is not None, "resume needs an earlier turn"
                        evs = stream(c, "GET", f"/api/agent/turns/{turn_id}/events?after={last_seq}")
                        first = last_seq + 1
                    else:
                        decision = "approve" if "approve" in step else "deny"
                        tool = step[decision]
                        confirms = [e for e in seen if e["type"] == "confirm" and e["tool"] == tool]
                        assert confirms, f"no confirm for {tool} to {decision}"
                        r = c.post(
                            "/api/agent/confirm",
                            json={"tool_run_id": confirms[-1]["tool_run_id"], "decision": decision},
                        )
                        assert r.status_code == 200, r.text
                        if "status" in step:
                            assert r.json()["status"] == step["status"], r.json()
                        first = None
                    if first is not None:  # one turn's events: numbered without gaps, then a terminal one
                        assert [e["seq"] for e in evs] == list(range(first, first + len(evs))), evs
                        last_seq = evs[-1]["seq"]
                        end = {step["drop_after"]} if "drop_after" in step else TERMINAL
                        assert evs[-1]["type"] in end, f"stream ended on {evs[-1]}"
                    seen += evs
                    check_events(evs, step.get("events", []))
                    for req in _listed(step.get("request")):
                        check_request(model_requests[mark:], req)
                except AssertionError as e:
                    raise AssertionError(f"{path.name} step {i}: {e}") from e
    finally:
        tool_registry.set_current(before)


@pytest.mark.parametrize("path", sorted(SCENARIOS.glob("*.yaml")), ids=lambda p: p.stem)
def test_scenario(path, app, login_as, model_requests, monkeypatch):
    run(path, app, login_as, model_requests, monkeypatch)


def test_removing_the_untrusted_fence_fails_a_scenario(app, login_as, model_requests, monkeypatch):
    monkeypatch.setattr(delimiters, "wrap_untrusted_external", lambda source, text: text)
    with pytest.raises(AssertionError, match="untrusted_external_content"):
        run(SCENARIOS / "untrusted_result_is_fenced.yaml", app, login_as, model_requests, monkeypatch)


def test_unknown_keys_fail_loudly(tmp_path):
    bad = tmp_path / "sf-scen-typo.yaml"
    bad.write_text("name: typo\nsteps:\n  - send: hi\n    event: [done]\n")
    with pytest.raises(AssertionError, match="unknown keys"):
        load(bad)
