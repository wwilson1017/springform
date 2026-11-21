"""One model step's lookups run together; everything else keeps the model's order (agent.md §5, "One step's calls")."""

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from backend.core import db as core_db
from backend.core.agent import dispatch, loop_guard, registry as tool_registry, turn_hooks
from backend.core.agent.providers import fake
from backend.core.agent.spec import ToolSpec

LIST = {"tool": "example_list_widgets", "args": {}}
OTHER = {"tool": "example_list_widgets", "args": {"q": "z"}}
SCHEMA = {"type": "object", "properties": {}}


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


@pytest.fixture
def tools(app):
    """add(*specs): test tools on top of the live registry. core_jot is a routine local write."""
    before = tool_registry.current()

    def add(*specs, log=None):
        jot = ToolSpec(
            name="core_jot",
            description="Jot.",
            input_schema=SCHEMA,
            writes=True,
            confirm_tier="routine",
            handler_in=lambda conn, u, a: (log.append("jot") if log is not None else None) or {"ok": True},
            targets=lambda a: [],
        )
        tool_registry.set_current(tool_registry.build_registry([*before.all(), jot, *specs]))

    yield add
    tool_registry.set_current(before)


def read(name: str, handler, **flags) -> ToolSpec:
    return ToolSpec(name=name, description="A lookup.", input_schema=SCHEMA, writes=False, handler=handler, **flags)


def test_two_lookups_run_together_and_a_write_of_the_step_runs_after_both(login_as, tools, model_requests):
    both, log = threading.Barrier(2), []

    def look(user, args):
        both.wait(timeout=5)  # passes only while the other lookup is in its handler too
        log.append("look")
        return {"shelf": args.get("shelf")}

    tools(read("core_look", look), log=log)
    fake.script(
        [
            {"tool": "core_jot"},
            {"tool": "core_look", "args": {"shelf": "a"}},
            {"tool": "core_look", "args": {"shelf": "b"}},
        ],
        "ok",
    )
    evs = chat(login_as("member"), message="go")
    assert [e["status"] for e in of(evs, "tool_end")] == ["done"] * 3 and log == ["look", "look", "jot"]
    results = [b["content"] for b in model_requests[-1]["messages"][-1]["content"]]
    assert results == ['{"ok": true}', '{"shelf": "a"}', '{"shelf": "b"}']  # the model's call order


def test_at_most_four_lookups_run_at_once(login_as, tools):
    lock, now, peak = threading.Lock(), [0], [0]

    def look(user, args):
        with lock:
            now[0] += 1
            peak[0] = max(peak[0], now[0])
        time.sleep(0.1)
        with lock:
            now[0] -= 1
        return {}

    tools(read("core_look", look))
    fake.script([{"tool": "core_look", "args": {"n": i}} for i in range(9)], "ok")
    evs = chat(login_as("member"), message="go")
    assert len(of(evs, "tool_end")) == 9 and 1 < peak[0] <= dispatch.MAX_PARALLEL == 4


def test_hooks_see_results_in_call_order_and_a_refused_lookup_is_not_run(login_as, tools, monkeypatch):
    ran, asked, shown = [], [], []

    def look(user, args):
        time.sleep(args["wait"])
        ran.append(args["n"])
        return {}

    def before(state, call):
        asked.append(call["args"]["n"])
        return "Blocked here." if call["args"]["n"] == 2 else None

    tools(read("core_look", look))
    monkeypatch.setitem(turn_hooks.REGISTERED, "before_tool", [before])
    point = turn_hooks.REGISTERED["on_tool_result"]
    monkeypatch.setitem(
        turn_hooks.REGISTERED, "on_tool_result", [*point, lambda s, call, run: shown.append(call["args"]["n"])]
    )
    fake.script([{"tool": "core_look", "args": {"n": n, "wait": w}} for n, w in ((1, 0.3), (2, 0), (3, 0))], "ok")
    ends = of(chat(login_as("member"), message="go"), "tool_end")
    assert ran == [3, 1] and asked == [1, 2, 3] and shown == [1, 3]  # the slow first call is still observed first
    assert sorted(e["status"] for e in ends) == ["done", "done", "error"]
    assert [e["result"] for e in ends if e["status"] == "error"] == [{"error": "Blocked here."}]


def test_a_write_and_a_second_untrusted_lookup_see_the_taint_of_the_first(login_as, tools):
    tools(read("core_page", lambda u, a: "a page", untrusted_source=True))
    # the routine write is called first and still runs after the page read, so it asks like any write after it
    fake.script([{"tool": "core_jot"}, {"tool": "core_page"}, LIST, {"tool": "core_page"}], "Two things wait.")
    evs = chat(login_as("member"), message="go")
    assert [e["tool"] for e in of(evs, "confirm")] == ["core_jot", "core_page"]
    assert sorted(e["tool"] for e in of(evs, "tool_end")) == ["core_page", "example_list_widgets"]
    assert core_db.one("SELECT tainted FROM core_agent_conversations WHERE id = ?", (evs[0]["id"],))["tainted"] == 1


def test_lookups_that_ran_stand_when_the_first_result_halts_and_the_rest_is_refused(login_as, monkeypatch):
    monkeypatch.setattr(loop_guard, "MAX_STRIKES", 1)
    fake.script(LIST, LIST, [LIST, OTHER, {"tool": "example_create_widget", "args": {"name": "x"}}])
    evs = chat(login_as("member"), message="list")
    ends = of(evs, "tool_end")
    assert [e["status"] for e in ends] == ["done"] * 4 + ["error"]
    assert ends[-1]["result"] == {"error": "Not run: the turn was stopped."} and not of(evs, "confirm")
    assert "after 4 tool calls" in of(evs, "text")[-1]["text"] and evs[-1]["type"] == "done"


def test_a_lookup_that_would_start_after_the_deadline_is_not_run(login_as, monkeypatch):
    monkeypatch.setattr(dispatch, "BATCH_SECONDS", 0)
    fake.script([LIST, OTHER], "ok")
    evs = chat(login_as("member"), message="list")
    ends = of(evs, "tool_end")
    assert [e["result"] for e in ends] == [{"error": dispatch.LATE}] * 2 and of(evs, "text")[-1]["text"] == "ok"
    rows = core_db.rows("SELECT status FROM core_agent_tool_runs WHERE conversation_id = ?", (evs[0]["id"],))
    assert [r["status"] for r in rows] == ["error", "error"]


def test_stop_waits_for_the_lookups_that_are_running(app, login_as, tools):
    inside, release = threading.Semaphore(0), threading.Event()

    def look(user, args):
        inside.release()
        release.wait(timeout=5)
        return {}

    tools(read("core_look", look))
    a = login_as("member")
    fake.script([{"tool": "core_look", "args": {"n": 1}}, {"tool": "core_look", "args": {"n": 2}}], "never")
    with TestClient(app, headers={"Authorization": f"Bearer {a.cookies.get('sf_session')}"}) as c:
        with c.stream("POST", "/api/agent/chat", json={"message": "go"}) as r:
            lines = r.iter_lines()
            first = json.loads(next(line for line in lines if line.startswith("data: "))[6:])
            assert inside.acquire(timeout=5) and inside.acquire(timeout=5)  # both are in their handlers
            assert c.post(f"/api/agent/turns/{first['turn_id']}/cancel").json() == {"cancelled": True}
            release.set()
            rest = [json.loads(line[6:]) for line in lines if line.startswith("data: ")]
        assert rest[-1]["type"] == "done" and rest[-1]["stopped"] is True
        rows = core_db.rows("SELECT status FROM core_agent_tool_runs WHERE conversation_id = ?", (first["id"],))
        assert [r["status"] for r in rows] == ["done", "done"]  # neither left `executing`


def test_a_routine_write_called_before_a_single_web_read_asks(login_as, tools):
    tools(read("core_page", lambda u, a: "a page", untrusted_source=True))
    fake.script([{"tool": "core_jot"}, {"tool": "core_page"}], "It waits.")
    evs = chat(login_as("member"), message="go")
    assert [e["tool"] for e in of(evs, "confirm")] == ["core_jot"]
    assert [e["tool"] for e in of(evs, "tool_end")] == ["core_page"]


def test_a_hook_that_halts_before_the_lookups_start_stops_them(login_as, tools, monkeypatch):
    ran = []
    tools(read("core_look", lambda u, a: ran.append(a["n"]) or {}))

    def before(state, call):
        state.halt = "a hook stopped it"

    monkeypatch.setitem(turn_hooks.REGISTERED, "before_tool", [before])
    fake.script([{"tool": "core_look", "args": {"n": n}} for n in (1, 2)])
    ends = of(chat(login_as("member"), message="go"), "tool_end")
    assert ran == [] and [e["result"] for e in ends] == [{"error": "Not run: the turn was stopped."}] * 2
