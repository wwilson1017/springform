"""Compaction's quality guard (what a summary must keep, retries, the timeout fallback) and the
memory flush before it. The end-to-end paths are the `compaction_*` scenarios."""

import asyncio
import json

import pytest

from backend.core import db as core_db, settings
from backend.core.agent import assembly, compaction, delimiters, history
from backend.core.agent.providers import fake
from backend.core.agent.providers.fake import FakeProvider
from backend.core.memory import jobs as memory_jobs

DEAL = [
    "Hello.",
    "Deal 4521 is worth 1250.00 and closes 2026-12-01.",
    "Invoice INV-0042 belongs to it.",
    "What do we know about the deal?",
]


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    fake.reset()
    yield
    fake.reset()


def chat(client, message: str, cid: int | None = None) -> int:
    r = client.post("/api/agent/chat", json={"message": message, **({"conversation_id": cid} if cid else {})})
    assert r.status_code == 200, r.text
    return json.loads(r.text.splitlines()[0][6:])["id"]


def thread(client, messages: list[str], cid: int | None = None) -> int:
    for m in messages:
        fake.script(f"Noted: {m}")
        cid = chat(client, m, cid)
    assert cid is not None
    return cid


def test_identifiers_are_taken_whole():
    text = (
        "Deal 4521 is worth 1250.00, $1,250.00 or $40; closes 2026-12-01 (at 2026-11-21T10:00:00Z). "
        'See https://example.com/a?b=1. Invoice INV-0042, ticket #17, pi 3.14159. {"deal_id": 17}'
    )
    fence = delimiters.wrap_untrusted_external("t", "nothing")
    assert compaction.identifiers([text, fence]) == [
        "4521", "1250.00", "$1,250.00", "$40", "2026-12-01", "2026-11-21",
        "https://example.com/a?b=1", "INV-0042", "#17", "17",
    ]  # fmt: skip


def test_identifiers_in_json_are_read_decoded_not_from_escapes():
    args = json.dumps({"customer": "Zoé Márquez", "note": "line1\nINV-0042", "due": "a\n2026-12-01"})
    result = json.dumps({"order_id": 7, "memo": "paid\tSO-7781 😀"})
    found = compaction.identifiers([args, result])
    assert found == ["INV-0042", "2026-12-01", "SO-7781", "7"]
    assert not any(t.startswith(("n", "u00", "ud8")) for t in found)


def test_missing_matches_whole_tokens():
    assert compaction.missing("deal 45210, invoice inv-0042", ["4521", "INV-0042"]) == ["4521", "INV-0042"]
    assert compaction.missing("Deal 4521 (INV-0042).", ["4521", "INV-0042"]) == []
    assert compaction.missing("Quoted:  Invoice\nINV-0042 belongs to it.", ["Invoice INV-0042 belongs to it."]) == []


def test_required_puts_the_latest_ask_first_and_keeps_the_previous_gists_identifiers():
    def row(i, role, text, **content):
        return {"id": i, "role": role, "content": {"text": text, **content}}

    middle = [
        row(3, "user", "Deal 4521 is worth 1250.00."),
        row(4, "assistant", "", tool_calls=[{"tool_use_id": "t1", "tool": "crm_get", "args": {"deal_id": 9}}]),
        row(5, "user", "Invoice INV-0042 belongs to it. " + "x " * 200),
    ]
    runs = {4: [{"tool_use_id": "t1", "status": "done", "result": json.dumps({"url": "https://example.com/d/9"})}]}
    prev = delimiters.wrap_conversation_summary("## Exact identifiers\nSO-7781")
    must = compaction.required(middle, runs, prev)
    assert must[0].startswith("Invoice INV-0042 belongs to it. x") and len(must[0]) <= compaction.MAX_ASK_CHARS
    assert must[1:] == ["9", "https://example.com/d/9", "4521", "1250.00", "SO-7781"]  # newest rows first


def test_a_lossy_summary_is_retried_naming_what_is_missing_then_rejected(monkeypatch):
    prompts = []

    async def lossy(system, prompt, **kw):
        prompts.append(prompt)
        return "## Exact identifiers\nThe deal closes 2026-12-01."

    monkeypatch.setattr(compaction, "acomplete", lossy)
    middle = [{"id": 3, "role": "user", "content": {"text": "Deal 4521 is worth 1250.00, closing 2026-12-01."}}]
    assert asyncio.run(compaction._summarize(middle, {}, None)) == ("", "rejected")
    assert len(prompts) == 1 + compaction.SUMMARY_RETRIES
    assert "YOUR LAST SUMMARY" not in prompts[0]
    for p in prompts[1:]:
        assert "must appear exactly as written:\n- Deal 4521 is worth 1250.00, closing 2026-12-01.\n" in p


def test_a_summary_fixed_on_retry_is_kept(monkeypatch):
    replies = iter(["Deal closes soon.", "## Pending user asks\nDeal 4521 is worth 1250.00."])

    async def complete(system, prompt, **kw):
        return next(replies)

    monkeypatch.setattr(compaction, "acomplete", complete)
    middle = [{"id": 3, "role": "user", "content": {"text": "Deal 4521 is worth 1250.00."}}]
    assert asyncio.run(compaction._summarize(middle, {}, None)) == (
        "## Pending user asks\nDeal 4521 is worth 1250.00.",
        "ok",
    )


def test_a_timed_out_summary_drops_the_oldest_rows_and_keeps_the_previous_gist(login_as, monkeypatch):
    a = login_as("member")
    monkeypatch.setattr(fake, "CONTEXT_WINDOW", 1000)
    cid = thread(a, DEAL[:3])
    fake.script(
        "Nothing to record.", "## Pending user asks\nInvoice INV-0042 belongs to it.\nDeal 4521, 1250.00, 2026-12-01"
    )
    cid = thread(a, DEAL[3:], cid)  # compacts with a good summary
    first = history.compaction_state(cid)
    assert "Deal 4521, 1250.00" in first["summary"]

    async def slow(system, prompt, **kw):
        await asyncio.sleep(5)

    monkeypatch.setattr(compaction, "acomplete", slow)
    monkeypatch.setattr(compaction, "SUMMARY_TIMEOUT", 0.05)
    fake.script("Noted: next")
    chat(a, "And the next step?", cid)
    state = history.compaction_state(cid)
    inner = delimiters.conversation_summary_text(state["summary"])
    assert inner.startswith("## Pending user asks\nInvoice INV-0042") and inner.endswith(compaction.DROPPED_NOTE)
    assert state["summary_first_kept_id"] > first["summary_first_kept_id"]
    sent = json.dumps(assembly.assemble_messages(FakeProvider("fake"), cid))
    assert "What do we know about the deal?" not in sent and "And the next step?" in sent


@pytest.fixture
def nightly_on(app):
    settings.set_setting(memory_jobs.ENABLED_SETTING, True, None)


def test_the_flush_waits_for_the_nightly_memory_pass(login_as, model_requests):
    a = login_as("member")
    cid = thread(a, DEAL)
    n = len(model_requests)
    assert asyncio.run(compaction._flush(cid, 10_000)) == 0 and len(model_requests) == n


def test_the_flush_records_facts_as_the_observer_and_reads_each_row_once(login_as, nightly_on, model_requests):
    a = login_as("member")
    cid = thread(a, DEAL)
    last_user = max(m["id"] for m in history.messages(cid) if m["role"] == "user")
    fake.script(
        [
            {"tool": "core_memory_remember", "args": {"text": "Deal 4521 is worth 1250.00."}},
            {"tool": "core_context_file_write", "args": {"filename": "soul.md", "content": "x"}},  # not offered
            {"tool": "core_memory_remember", "args": {"text": 42}},
        ]
    )
    assert asyncio.run(compaction._flush(cid, last_user)) == 1
    call = model_requests[-1]
    assert [t["name"] for t in call["tools"]] == ["core_memory_remember"]
    assert "Invoice INV-0042 belongs to it." in call["messages"][0]["content"]
    assert "Noted:" not in call["messages"][0]["content"]  # user rows only
    fact = core_db.one("SELECT * FROM core_agent_facts")
    assert (fact["text"], fact["author_user_id"], fact["source_conversation_id"]) == (
        "Deal 4521 is worth 1250.00.",
        0,
        cid,
    )
    assert json.loads(fact["tags"]) == ["observed", "compaction"]
    n = len(model_requests)
    assert asyncio.run(compaction._flush(cid, last_user)) == 0 and len(model_requests) == n  # already read
    obs = core_db.one("SELECT * FROM core_agent_observations WHERE conversation_id = ?", (cid,))
    assert obs["pending"] == 1  # the last user row is still the nightly observer's


@pytest.mark.parametrize("when", ["private", "tainted", "made private during the call"])
def test_the_flush_writes_nothing_for_a_private_or_tainted_conversation(login_as, nightly_on, monkeypatch, when):
    a = login_as("member")
    cid = thread(a, DEAL)
    if when == "private":
        a.patch(f"/api/agent/conversations/{cid}", json={"is_private": True})
    elif when == "tainted":
        history.mark_tainted(cid)
    else:
        original = FakeProvider.stream_turn

        def flip(self, *args, **kw):
            a.patch(f"/api/agent/conversations/{cid}", json={"is_private": True})
            return original(self, *args, **kw)

        monkeypatch.setattr(FakeProvider, "stream_turn", flip)
    fake.script({"tool": "core_memory_remember", "args": {"text": "Deal 4521 is worth 1250.00."}})
    assert asyncio.run(compaction._flush(cid, 10_000)) == 0
    assert core_db.one("SELECT count(*) AS n FROM core_agent_facts")["n"] == 0
