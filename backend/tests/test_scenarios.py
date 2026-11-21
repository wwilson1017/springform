"""Whisk scenarios: each `scenarios/*.yaml` scripts the FakeProvider, drives real turns over HTTP
(the server-owned turn in `detached.py` running `turns.TurnRunner`), and checks the events each step
emits and what the model was sent. The file format is in docs/agents/testing.md ("Whisk scenarios").

The client runs the app's lifespan (`with TestClient(app)`), so every request shares one event loop
and leaving a stream early is a real disconnect.
"""

import base64
import json
import re
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.core import clock, db as core_db
from backend.core.agent import delimiters, detached, engine, registry as tool_registry, turns
from backend.core.agent.providers import fake
from backend.core.agent.spec import ToolSpec
from backend.core.auth import service as auth_service
from backend.core.checkins import service as checkins

SCENARIOS = Path(__file__).parent / "scenarios"
TOP_KEYS = {"name", "role", "context_window", "tools", "records", "steps"}
FLAGS = ("confirm_tier", "always_confirm", "untrusted_source", "external_effect")
TOOL_KEYS = {"name", "description", "writes", "returns", "repeat", "delay", *FLAGS}
ACTIONS = {"send", "continue", "approve", "deny", "resume", "checkin", "undo"}
STEP_KEYS = ACTIONS | {
    *("sql", "replies", "drop_after", "steer", "events", "request", "status", "usage", "page", "record", "files"),
    *("reason", "always_allow"),  # the /confirm body of a deny or an approve
    "conversations",  # how many conversations the user has after the step
    "all",  # approve or deny every member of that card's batch, one /confirm each (what the client does)
}
STEER_KEYS = {"after", "message"}
FILE_KEYS = {"name", "text", "base64"}
REQUEST_KEYS = {
    *("call", "messages_contain", "messages_exclude", "messages_match", "system_contains", "system_exclude"),
    *("tools_include", "tools_exclude"),  # tool names offered to the model on that call
}
RECORD_KEYS = {"name", "private"}
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
        if "steer" in step:
            _strict(f"{path.name} step {i} steer", step["steer"], STEER_KEYS)
        for f in step.get("files", []):
            _strict(f"{path.name} step {i} file", f, FILE_KEYS)
    for tool in spec.get("tools", []):
        _strict(f"{path.name} tool", tool, TOOL_KEYS)
    for key, rec in (spec.get("records") or {}).items():
        _strict(f"{path.name} record {key}", rec, RECORD_KEYS)
    return spec


def _listed(value) -> list:
    return [] if value is None else value if isinstance(value, list) else [value]


def tool_spec(t: dict) -> ToolSpec:
    """A test-only core tool: a read, a local write (`handler_in`, no targets) or an external-effect
    write (`handler`), answering `returns` (default `{ok: true}`), or a list of `repeat` copies of it,
    after `delay` seconds when it runs through `handler`."""
    returns = t.get("returns", {"ok": True})
    if "repeat" in t:
        returns = [returns] * t["repeat"]
    writes = t.get("writes", False)
    local_write = writes and not t.get("external_effect")
    flags = {k: t[k] for k in FLAGS if k in t}
    return ToolSpec(
        name=t["name"],
        description=t.get("description", "A scenario tool."),
        input_schema={"type": "object", "properties": {}},
        writes=writes,
        handler=None if local_write else (lambda user, args: time.sleep(t.get("delay", 0)) or returns),
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


def make_records(records: dict, me: int) -> dict[str, int]:
    """Example widgets owned by another user, by key: readable unless `private`."""
    with core_db.transaction() as conn:
        owner = auth_service.create_user_in(conn, f"scen-owner-{me}@example.com", "Scenario Owner", "member")["id"]
        return {
            key: core_db.insert_in(
                conn,
                """INSERT INTO example_widgets (name, owner_user_id, is_private, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (rec["name"], owner, int(rec.get("private", False)), clock.now_iso(), clock.now_iso()),
            )
            for key, rec in records.items()
        }


def matches(event: dict, wanted) -> bool:
    """A string is a type; a mapping matches the keys it names."""
    wanted = {"type": wanted} if isinstance(wanted, str) else wanted
    return all(event.get(k) == v for k, v in wanted.items())


def check_events(evs: list[dict], wanted: list) -> None:
    """`wanted` appears in `evs` in order (other events may sit between), each as `matches` reads it."""
    it = iter(evs)
    for w in wanted:
        assert any(matches(e, w) for e in it), (
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
    for text in req.get("system_exclude", []):
        assert text not in system, f"model call {at}: system prompt contains {text!r}"
    names = {t["name"] for t in call["tools"]}
    for name in req.get("tools_include", []):
        assert name in names, f"model call {at}: {name!r} not offered (offered: {sorted(names)})"
    for name in req.get("tools_exclude", []):
        assert name not in names, f"model call {at}: {name!r} was offered"


def _job_idle(seconds: float = 5) -> None:
    """Wait out the check-in job's first pass at startup, so the step's own run is the one that runs it."""
    deadline = time.monotonic() + seconds
    while not core_db.one("SELECT 1 FROM core_job_runs WHERE job = ? AND status != 'running'", (checkins.JOB,)):
        assert time.monotonic() < deadline, "the check-in job's first pass never ended"
        time.sleep(0.02)


def stream(
    c: TestClient, method: str, url: str, drop_after: str | None = None, steer: dict | None = None, **kw
) -> list[dict]:
    """The turn's events. `steer` posts its message to the conversation, once, as soon as an event
    matches its `after`, while the turn runs: it must be queued (202)."""
    evs, cid = [], None
    with c.stream(method, url, **kw) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("data: "):
                evs.append(json.loads(line[6:]))
                cid = evs[0].get("id")
                if steer and matches(evs[-1], steer["after"]):
                    sent = c.post("/api/agent/chat", json={"conversation_id": cid, "message": steer["message"]})
                    assert sent.status_code == 202, sent.text
                    steer = None
                if drop_after and evs[-1]["type"] == drop_after:
                    break  # leaving the block disconnects
    assert steer is None, f"no event matched steer.after {steer and steer['after']}"
    return evs


def run(path: Path, app, login_as, model_requests: list[dict], monkeypatch) -> None:
    spec = load(path)
    if "context_window" in spec:
        monkeypatch.setattr(fake, "CONTEXT_WINDOW", spec["context_window"])
    before = tool_registry.current()
    tool_registry.set_current(tool_registry.build_registry([*before.all(), *map(tool_spec, spec.get("tools", []))]))
    who = login_as(spec.get("role", "member"))
    records = make_records(spec.get("records") or {}, who.principal.id)
    cid = turn_id = None
    last_seq = -1
    seen: list[dict] = []
    try:
        with TestClient(app, headers={"Authorization": f"Bearer {who.cookies.get('sf_session')}"}) as c:
            for i, step in enumerate(spec["steps"], 1):
                try:
                    with core_db.transaction() as conn:  # a change to the data between turns, made before the action
                        for statement in _listed(step.get("sql")):
                            conn.execute(statement)
                    fake.script(*step.get("replies", []))
                    mark = len(model_requests)
                    ledger = core_db.one("SELECT coalesce(max(id), 0) AS n FROM core_agent_usage")["n"]
                    evs: list[dict] = []
                    if "send" in step or "continue" in step:
                        body = {"message": step["send"]} if "send" in step else {}
                        if "page" in step:
                            body["page"] = step["page"]
                        if "record" in step:
                            body["record"] = {"entity_type": "example.widget", "entity_id": records[step["record"]]}
                        body |= {"conversation_id": cid} if cid else {}
                        files = [
                            (
                                "files",
                                (f["name"], base64.b64decode(f["base64"]) if "base64" in f else f["text"].encode()),
                            )
                            for f in step.get("files", [])
                        ]
                        kw = {"data": {"payload": json.dumps(body)}, "files": files} if files else {"json": body}
                        url = "/api/agent/chat/upload" if files else "/api/agent/chat"
                        evs = stream(c, "POST", url, step.get("drop_after"), step.get("steer"), **kw)
                        assert evs and evs[0]["type"] == "conversation_id", evs
                        cid, turn_id, first = evs[0]["id"], evs[0]["turn_id"], 0
                        if "drop_after" in step:  # the stream really dropped mid-turn, not after a buffered end
                            assert detached._live(turn_id) is not None, (
                                "the turn had already ended when the client left"
                            )
                    elif "checkin" in step:  # a scheduled check-in made due and run like the job runs it
                        made = c.post(
                            "/api/agent/checkins",
                            json={"name": "Scenario check-in", "prompt": step["checkin"], "schedule": "every:60"},
                        )
                        assert made.status_code == 200, made.text
                        _job_idle()
                        with core_db.transaction() as conn:
                            conn.execute(
                                "UPDATE core_agent_checkins SET next_run_at = ? WHERE id = ?",
                                ("2000-01-01T00:00:00Z", made.json()["id"]),
                            )
                        checkins.run_due()
                        first = None
                    elif "resume" in step:
                        assert turn_id is not None, "resume needs an earlier turn"
                        evs = stream(c, "GET", f"/api/agent/turns/{turn_id}/events?after={last_seq}")
                        first = last_seq + 1
                    elif "undo" in step:  # the Undo button of that tool's newest change list
                        runs = [e for e in seen if e["type"] in ("confirm", "tool_end") and e["tool"] == step["undo"]]
                        assert runs, f"no run of {step['undo']} to undo"
                        r = c.post(f"/api/agent/change-lists/{runs[-1]['tool_run_id']}/undo")
                        assert r.status_code == 200, r.text
                        if "status" in step:
                            assert r.json()["status"] == step["status"], r.json()
                        first = None
                    else:
                        decision = "approve" if "approve" in step else "deny"
                        tool = step[decision]
                        confirms = [e for e in seen if e["type"] == "confirm" and e["tool"] == tool]
                        assert confirms, f"no confirm for {tool} to {decision}"
                        extra = {k: step[k] for k in ("reason", "always_allow") if k in step}
                        newest = confirms[-1]
                        if step.get("all"):
                            assert newest.get("batch"), f"the newest confirm for {tool} has no batch"
                        members = [e for e in seen if e["type"] == "confirm" and e.get("batch") == newest.get("batch")]
                        for card in members if step.get("all") else [newest]:
                            r = c.post(
                                "/api/agent/confirm",
                                json={"tool_run_id": card["tool_run_id"], "decision": decision, **extra},
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
                    if "drop_after" not in step:  # a dropped turn may still be using its replies
                        assert not fake._script, (
                            f"{len(fake._script)} scripted replies left unused: {list(fake._script)}"
                        )
                    seen += evs
                    check_events(evs, step.get("events", []))
                    for req in _listed(step.get("request")):
                        check_request(model_requests[mark:], req)
                    if "conversations" in step:
                        n = core_db.one(
                            "SELECT count(*) AS n FROM core_agent_conversations WHERE user_id = ?", (who.principal.id,)
                        )
                        assert n["n"] == step["conversations"], (
                            f"{n['n']} conversations, wanted {step['conversations']}"
                        )
                    if "usage" in step:  # the ledger rows this step wrote, matched like `events`
                        check_events(
                            core_db.rows("SELECT * FROM core_agent_usage WHERE id > ? ORDER BY id", (ledger,)),
                            step["usage"],
                        )
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


def test_removing_the_upload_fence_fails_a_scenario(app, login_as, model_requests, monkeypatch):
    monkeypatch.setattr(delimiters, "wrap_untrusted_upload", lambda filename, text, image=False: text)
    with pytest.raises(AssertionError, match="untrusted_external_content"):
        run(SCENARIOS / "upload_is_fenced_and_read_back.yaml", app, login_as, model_requests, monkeypatch)


def test_unknown_keys_fail_loudly(tmp_path):
    bad = tmp_path / "sf-scen-typo.yaml"
    bad.write_text("name: typo\nsteps:\n  - send: hi\n    event: [done]\n")
    with pytest.raises(AssertionError, match="unknown keys"):
        load(bad)


def test_a_rule_that_ignores_taint_fails_the_scenario(app, login_as, model_requests, monkeypatch):
    real = engine.rule_eligible
    monkeypatch.setattr(engine, "rule_eligible", lambda spec, args, tainted: real(spec, args, False))
    with pytest.raises(AssertionError, match="confirm"):
        run(SCENARIOS / "always_allow_never_skips_a_tainted_turn.yaml", app, login_as, model_requests, monkeypatch)


def test_a_checkin_offered_chat_tools_fails_the_scenario(app, login_as, model_requests, monkeypatch):
    real = turns.chat_tools
    monkeypatch.setattr(turns, "chat_tools", lambda user, source="chat": real(user))
    with pytest.raises(AssertionError, match="core_scen_save_widget"):
        run(SCENARIOS / "checkin_reads_only_and_silent_leaves_nothing.yaml", app, login_as, model_requests, monkeypatch)
