"""Big tool results (agent.md §5, "Result cap and in-turn clearing"): the model sees head + tail with a
handle, in its own turn and every later one, and `core_read_result` gives back the whole text."""

import json

import pytest

from backend.core import db
from backend.core.agent import assembly, history, registry as tool_registry, result_cap, turn_hooks
from backend.core.agent.providers import fake
from backend.core.agent.providers.fake import FakeProvider
from backend.core.agent.spec import ToolSpec

SCHEMA = {"type": "object", "properties": {}}
BIG = "".join(f"line {i:05d} " + "x" * 40 + "\n" for i in range(1500))  # ~73k characters
ROWS = [{"id": i, "name": f"widget {i}", "colour": "blue", "size": i % 7} for i in range(2000)]


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    fake.reset()
    yield
    fake.reset()


@pytest.fixture
def tools(app):
    before = tool_registry.current()

    def spec(name, result, **kw):
        return ToolSpec(
            name=name, description=name, input_schema=SCHEMA, writes=False, handler=lambda u, a: result, **kw
        )

    tool_registry.set_current(
        tool_registry.build_registry(
            [
                *before.all(),
                spec("core_big_text", BIG),
                spec("core_big_rows", ROWS),
                spec("core_big_confirmed", BIG, always_confirm=True),
                spec("core_big_remote", ROWS, untrusted_source=True),
            ]
        )
    )
    yield
    tool_registry.set_current(before)


@pytest.fixture
def views(monkeypatch):
    """The messages each model call is sent."""
    seen: list[list[dict]] = []
    point = turn_hooks.REGISTERED["before_model_call"]
    monkeypatch.setitem(turn_hooks.REGISTERED, "before_model_call", [*point, lambda s: seen.append(list(s.messages))])
    return seen


def chat(client, **body) -> list[dict]:
    r = client.post("/api/agent/chat", json=body)
    assert r.status_code == 200, r.text
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


def of(evs, kind) -> list[dict]:
    return [e for e in evs if e["type"] == kind]


def results(messages) -> list[str]:
    return [
        b["content"]
        for m in messages
        if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"]
        if b.get("type") == "tool_result"
    ]


def read_all(client, cid, handle) -> str:
    """Page core_read_result from offset 0 to the end; the joined text."""
    text, offset = "", 0
    while True:
        evs = chat(
            client,
            conversation_id=cid,
            message=f"/tool core_read_result {json.dumps({'handle': handle, 'offset': offset})}",
        )
        page = of(evs, "tool_end")[0]["result"]
        header, _, body = page.partition("\n")
        text += body
        if "end of result" in header:
            return text
        offset = int(header.rsplit("offset=", 1)[1].rstrip("]"))


def test_small_results_pass_untouched():
    small = "x" * result_cap.CAP_CHARS
    assert result_cap.capped(small, 1) is small
    assert result_cap.capped({"not": "text"}, 1) == {"not": "text"}


def test_capped_text_keeps_head_and_tail_at_line_breaks():
    view = result_cap.capped(BIG, 412)
    head, _, rest = view.partition("\n[... ")
    tail = rest.split(" characters omitted ...]\n", 1)[1].split("\n\n[Result capped:", 1)[0]
    assert head.startswith("line 00000") and head.endswith("x\n") and BIG.startswith(head)
    assert tail.startswith("line ") and BIG.endswith(tail)
    assert f'core_read_result(handle="r412", offset={len(head)})' in view
    assert len(view) < result_cap.CAP_CHARS and result_cap.capped(view, 412) == view


@pytest.mark.parametrize(
    "value,csv",
    [
        ([{"a": 1, "b": 2, "c": 3}] * 2, False),  # two rows
        ([{"a": 1, "b": 2, "c": 3}] * 3, True),
        ([{"a": 1, "b": 2}] * 3, False),  # two fields
        ([{"a": 1, "b": 2, "c": 3}] * 17 + [{"a": 1, "b": 2}] * 3, False),  # c in 85% of rows
        ({"total": 3, "rows": [{"a": 1, "b": 2, "c": None}] * 3}, True),
        ({"total": 3, "rows": [1, 2, 3]}, False),
    ],
)
def test_uniform_arrays_become_csv(value, csv):
    text = json.dumps(value)
    out = result_cap._as_csv(text)
    assert (out is not None) == csv
    assert out is None or ("[CSV: " in out and "a,b,c" in out)


def test_a_list_that_fits_once_it_is_csv_is_not_capped():
    rows = [{"id": i, "name": f"w{i}", "colour": "blue"} for i in range(600)]
    text = json.dumps(rows)
    assert len(text) > result_cap.CAP_CHARS
    view = result_cap.capped(text, 1)
    assert view.startswith("[CSV: result, 600 rows x 3 fields]\nid,name,colour\n0,w0,blue\n")
    assert "Result capped" not in view


@pytest.mark.parametrize("tool", ["core_big_text", "core_big_rows"])
def test_a_capped_result_is_fully_readable_via_read_result(login_as, tools, views, tool):
    a = login_as("member")
    evs = chat(a, message=f"/tool {tool} {{}}")
    end, cid = of(evs, "tool_end")[0], evs[0]["id"]
    run = db.must(history.get_tool_run(end["tool_run_id"]))
    whole = BIG if tool == "core_big_text" else json.dumps(ROWS)
    assert history.model_content(run) == whole  # stored whole
    [shown] = results(views[1])
    assert "Result capped" in shown and len(shown) < result_cap.CAP_CHARS
    handle = f"r{run['id']}"
    assert read_all(a, cid, handle) == result_cap.full_text(history.model_content(run))


def test_later_turns_and_a_rebuild_see_the_same_capped_view(login_as, tools, views):
    a = login_as("member")
    cid = chat(a, message="/tool core_big_text {}")[0]["id"]
    [shown] = results(views[1])
    rebuilt = results(assembly.assemble_messages(FakeProvider("fake"), cid))
    assert rebuilt == [shown] and "line 00700" not in shown


def test_a_confirmed_tools_big_result_is_capped_and_readable(login_as, tools, views):
    a = login_as("member")
    evs = chat(a, message="/tool core_big_confirmed {}")
    confirm, cid = of(evs, "confirm")[0], evs[0]["id"]
    r = a.post("/api/agent/confirm", json={"tool_run_id": confirm["tool_run_id"], "decision": "approve"}).json()
    assert r["status"] == "done"
    views.clear()
    assert chat(a, conversation_id=cid)[-1]["type"] == "done"
    assert any("Result capped" in c for c in results(views[0]))
    assert read_all(a, cid, f"r{confirm['tool_run_id']}") == BIG


def test_grep_returns_offsets_and_context(login_as, tools):
    a = login_as("member")
    evs = chat(a, message="/tool core_big_text {}")
    handle, cid = f"r{of(evs, 'tool_end')[0]['tool_run_id']}", evs[0]["id"]
    evs = chat(
        a, conversation_id=cid, message=f"/tool core_read_result {json.dumps({'handle': handle, 'grep': 'LINE 01234'})}"
    )
    out = of(evs, "tool_end")[0]["result"]
    offset = BIG.index("line 01234")
    assert out.startswith(f'[{handle}: 1 matches for "LINE 01234"]\n@{offset}: ')


def test_read_result_is_owner_and_conversation_bound(login_as, tools):
    a, b = login_as("member"), login_as("member")
    evs = chat(a, message="/tool core_big_text {}")
    handle, cid = f"r{of(evs, 'tool_end')[0]['tool_run_id']}", evs[0]["id"]
    other = chat(a, message="hello")[0]["id"]
    small = of(chat(a, conversation_id=cid, message="/tool example_list_widgets {}"), "tool_end")[0]["tool_run_id"]

    def read(client, handle, **body):
        evs = chat(client, **body, message=f"/tool core_read_result {json.dumps({'handle': handle})}")
        return of(evs, "tool_end")[0]

    assert read(a, handle, conversation_id=cid)["status"] == "done"
    for client, h, body in [
        (b, handle, {}),  # another member
        (a, handle, {"conversation_id": other}),  # the owner, from another conversation
        (a, "r999999", {"conversation_id": cid}),
        (a, "nonsense", {"conversation_id": cid}),
    ]:
        end = read(client, h, **body)
        assert end["status"] == "error" and "No stored result" in end["result"]["error"]
    history.resolve(small, "error", error="x", expect="done")  # a run that is not done
    assert read(a, f"r{small}", conversation_id=cid)["status"] == "error"


def test_read_result_expires_after_24_hours(login_as, tools, freeze):
    freeze("2026-11-01T09:00:00Z")
    a = login_as("member")
    evs = chat(a, message="/tool core_big_text {}")
    handle, cid = f"r{of(evs, 'tool_end')[0]['tool_run_id']}", evs[0]["id"]
    freeze("2026-11-02T09:00:01Z")
    evs = chat(a, conversation_id=cid, message=f"/tool core_read_result {json.dumps({'handle': handle})}")
    assert "more than 24 hours old" in of(evs, "tool_end")[0]["result"]["error"]


def test_an_untrusted_result_stays_fenced_when_capped_and_when_read(login_as, tools, views):
    a = login_as("member")
    evs = chat(a, message="/tool core_big_remote {}")
    end, cid = of(evs, "tool_end")[0], evs[0]["id"]
    [shown] = results(views[1])
    nonce = shown.split('id="', 1)[1].split('"', 1)[0]
    assert shown.startswith("<untrusted_external_content") and "[CSV: result, 2000 rows x 4 fields]" in shown
    close = f'</untrusted_external_content id="{nonce}">'
    assert shown.index(close) < shown.index("[Result capped")  # the notice sits outside the data
    evs = chat(
        a,
        conversation_id=cid,
        message=f"/tool core_read_result {json.dumps({'handle': f'r{end["tool_run_id"]}', 'offset': 30000})}",
    )
    page = of(evs, "tool_end")[0]["result"]
    assert page.startswith("<untrusted_external_content") and page.rstrip().endswith(">")


def test_read_result_is_not_offered_over_mcp(app):
    assert "core_read_result" not in {s.name for s in tool_registry.current().for_source("mcp")}
    assert "core_read_result" in {s.name for s in tool_registry.current().for_source("chat")}


def test_deeply_nested_json_is_capped_as_text():
    deep = "[" * 30_000 + "]" * 30_000
    assert "Result capped" in result_cap.capped(deep, 1)


def test_rows_that_each_add_keys_are_not_tabled():
    rows = [{"a": 1, "b": 2, "c": 3, f"k{i}": i} for i in range(4000)]
    assert result_cap._as_csv(json.dumps(rows)) is None


def test_grep_is_a_literal_and_bounded():
    assert result_cap._grep("r1", "a" * 400_000, "a" * 190 + "b").startswith('[r1: 0 matches for "')
    assert "@3: xx Hello" in result_cap._grep("r1", "xx Hello .*", "HELLO")
    near = result_cap._grep("r1", "id-7 id-7 id-7", "id-7")
    assert near.startswith('[r1: 3 matches for "id-7", 1 shown]') and near.count("@") == 1
    assert result_cap._grep("r1", "x.*y", ".*").startswith('[r1: 1 matches for ".*"]')
    with pytest.raises(result_cap.Invalid):
        result_cap._grep("r1", "text", "x" * (result_cap.GREP_MAX_CHARS + 1))
