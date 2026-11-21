"""The usage ledger (agent.md §5, "Usage ledger"): every model call writes a priced row, and the
admin's Usage card reads this month's total."""

import json

import pytest

from backend.core import db as core_db, settings
from backend.core.agent import usage
from backend.core.agent.providers import fake
from backend.core.memory import jobs

RATES = {
    "fake-default": {"input": 1.0, "output": 2.0, "cache_read": 0.0, "cache_write": 0.0},
    "fake-light": {"input": 3.0, "output": 4.0, "cache_read": 0.0, "cache_write": 0.0},
}


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    fake.reset()
    yield
    fake.reset()


def rows() -> list[dict]:
    return core_db.rows("SELECT * FROM core_agent_usage ORDER BY id")


def chat(client, **body) -> list[dict]:
    r = client.post("/api/agent/chat", json=body)
    assert r.status_code == 200, r.text
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


def priced(row: dict) -> int:
    rate = RATES[row["model"]]
    return round(row["input_tokens"] * rate["input"] + row["output_tokens"] * rate["output"])


@pytest.fixture
def admin(login_as):
    a = login_as("admin")
    assert a.put("/api/core/settings", json={"values": {usage.RATES_SETTING: RATES}}).status_code == 200
    return a


def test_cost_is_tokens_times_rate_and_absent_without_one():
    counts = {"input": 1000, "output": 200, "cache_read": 5000, "cache_write": 300}
    # 1000 x 4 + 200 x 20 + 5000 x 0.2 + 300 x 5 micro-dollars
    assert usage.cost_micros("claude-opus-5-5", counts, usage.DEFAULT_RATES) == 10_500
    assert usage.cost_micros("claude-opus-5-5-preview", counts, usage.DEFAULT_RATES) is None  # exact names only


def test_seed_rates_cover_the_default_models():
    from backend.core.agent.providers.credentials import DEFAULT_MODELS

    assert {m for tiers in DEFAULT_MODELS.values() for m in tiers.values()} <= set(usage.DEFAULT_RATES)
    assert usage.check_rates(usage.DEFAULT_RATES) == usage.DEFAULT_RATES


@pytest.mark.parametrize(
    "bad",
    [
        [],
        {"m": {"input": -1}},
        {"m": {"input": True}},
        {"m": {"input": float("inf")}},
        {"m": {"input": float("nan")}},
        {"m": {"input": 10_001}},
        {"m": {"tip": 1}},
        {"m": 3},
        {"": {"input": 1}},
    ],
)
def test_bad_rates_are_refused(bad):
    with pytest.raises(ValueError):
        usage.check_rates(bad)


def test_missing_rate_fields_are_zero():
    assert usage.check_rates({"m": {"input": 2}}) == {
        "m": {"input": 2.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0}
    }


def test_rates_are_an_admin_setting_with_list_prices_as_default(admin, login_as):
    body = admin.get("/api/core/settings").json()
    assert body["defaults"][usage.RATES_SETTING] == usage.DEFAULT_RATES
    assert body["values"][usage.RATES_SETTING] == RATES
    assert (
        admin.put("/api/core/settings", json={"values": {usage.RATES_SETTING: {"m": {"input": -1}}}}).status_code == 422
    )
    r = admin.delete(f"/api/core/settings/{usage.RATES_SETTING}")
    assert r.json()["values"][usage.RATES_SETTING] == usage.DEFAULT_RATES
    member = login_as("member")
    assert member.put("/api/core/settings", json={"values": {usage.RATES_SETTING: {}}}).status_code == 403


def test_a_chat_turn_records_each_model_call_with_cost(admin):
    fake.script({"tool": "core_memory_search", "args": {"query": "widgets"}}, "Nothing about widgets.")
    evs = chat(admin, message="What do we know about widgets?")
    assert evs[-1]["type"] == "done"
    got = rows()
    assert [(r["source"], r["provider"], r["model"]) for r in got] == [("chat", "fake", "fake-default")] * 2
    for r in got:
        assert (r["conversation_id"], r["user_id"]) == (evs[0]["id"], admin.user["id"])
        assert r["input_tokens"] > 0 and r["cost_micros"] == priced(r) > 0


def test_a_fallback_records_the_model_that_answered(admin):
    fake.script({"error": "overloaded", "status": 529, "code": "overloaded_error"}, "from the light model")
    assert chat(admin, message="hi")[-1]["model"] == "fake-light"
    assert [(r["source"], r["model"]) for r in rows()] == [("chat", "fake-light")]  # the failed call wrote none


def test_a_compaction_records_its_summary_call(admin, monkeypatch):
    monkeypatch.setattr(fake, "CONTEXT_WINDOW", 20_000)
    cid = None
    for i in range(12):
        evs = chat(admin, message=f"turn {i} " + "lorem ipsum " * 300, **({"conversation_id": cid} if cid else {}))
        cid = evs[0]["id"]
        if any(e["type"] == "compacted" for e in evs):
            break
    else:
        pytest.fail("never compacted")
    summary = [r for r in rows() if r["source"] == "compaction"]
    assert len(summary) == 1 and summary[0]["model"] == "fake-light"
    assert (summary[0]["conversation_id"], summary[0]["user_id"]) == (cid, admin.user["id"])
    assert summary[0]["cost_micros"] == priced(summary[0]) > 0


def test_an_observer_run_records_its_call(admin):
    chat(admin, message="Our widgets ship from the north warehouse on Mondays.")
    settings.set_setting(jobs.ENABLED_SETTING, True, None)
    fake.script('{"facts": ["Widgets ship from the north warehouse on Mondays."]}')
    assert jobs.nightly()["observer"]["facts"] == 1
    seen = [r for r in rows() if r["source"] == "observer"]
    assert len(seen) == 1 and seen[0]["model"] == "fake-light" and seen[0]["user_id"] is None
    assert seen[0]["cost_micros"] == priced(seen[0]) > 0


def test_a_ledger_failure_never_fails_the_turn(admin, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(usage, "record_in", broken)
    assert chat(admin, message="hi")[-1]["type"] == "done"
    assert rows() == []


def test_usage_route_sums_this_local_month(admin, login_as, freeze):
    settings.set_setting("timezone", "America/Chicago", None)
    freeze("2026-11-15T12:00:00Z")

    def add(at: str, model: str, cost: int | None, cache_read: int = 0) -> None:
        with core_db.transaction() as conn:
            conn.execute(
                """INSERT INTO core_agent_usage (at, source, provider, model, input_tokens, output_tokens,
                       cache_read, cache_write, cost_micros) VALUES (?, 'chat', 'fake', ?, 100, 10, ?, 0, ?)""",
                (at, model, cache_read, cost),
            )

    add("2026-11-01T04:30:00Z", "fake-default", 999)  # 23:30 on 31 October in Chicago: last month
    add("2026-11-01T05:30:00Z", "fake-default", 120, cache_read=300)
    add("2026-11-10T09:00:00Z", "fake-default", 80, cache_read=100)
    add("2026-11-10T09:00:00Z", "some-new-model", None)

    assert login_as("member").get("/api/agent/usage").status_code == 403
    body = admin.get("/api/agent/usage").json()
    assert body["month"] == "2026-11" and body["cost_micros"] == 200
    by_model = {r["model"]: r for r in body["rows"]}
    assert by_model["fake-default"]["calls"] == 2 and by_model["fake-default"]["unpriced"] == 0
    assert by_model["some-new-model"]["unpriced"] == 1 and by_model["some-new-model"]["cost_micros"] == 0
    assert body["cache_hit_rate"] == pytest.approx(400 / (300 + 400))
