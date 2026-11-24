"""core_request_search and core_request_file: filing always waits for the Approve card, the server
writes the reporter, Via and the version, Whisk's labels mark the kind and open questions, an
expired token says so, and the filing tool is offered only while GitHub is connected."""

import json

import pytest

from backend.core import VERSION
from backend.core.agent import engine, registry
from backend.core.agent.providers import fake
from backend.core.requests import tools as req_tools
from backend.tests import test_requests_github as gh_tests
from backend.tests.test_core_contact_tools import approve, call, propose

gh = gh_tests.gh  # the fake GitHub fixture


@pytest.fixture(autouse=True)
def _fake_provider(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    yield
    fake.reset()


DRAFT = {
    "title": "Order list hides the delivery date",
    "app": "example",
    "kind": "bug",
    "description": "## Steps\n1. Open orders\n\n## Expected\nA date column\n\n## Actual\nNone",
    "open_questions": ["Local or UTC date?", "  "],
}


def test_filing_waits_for_approval_and_the_server_writes_who_and_what(login_as, gh):
    admin, member = login_as("admin"), login_as("member")
    gh_tests._configure(admin)
    run_id = propose(member, req_tools.FILE, **DRAFT, reporter="Somebody Else")
    assert gh.calls == [], "nothing leaves the install before Approve"
    out = approve(member, run_id)
    assert out["status"] == "done", out
    assert out["result"]["url"] == f"https://github.com/{gh_tests.REPO}/issues/1"
    sent = json.loads(gh.calls[0].content)
    assert sent["labels"] == ["request", "app:example", "bug", "needs-spec"]
    assert sent["body"] == (
        f"**Requested by:** {member.user['name']}\n**Via:** Whisk\n**App:** Example (`example`)\n"
        f"**Version:** {VERSION}\n\n{DRAFT['description']}\n\n## Open questions\n\n- Local or UTC date?"
    )
    assert "Somebody Else" not in sent["body"]

    found = call(member.principal, req_tools.SEARCH, query="DELIVERY")["requests"]
    assert [r["issue_number"] for r in found] == [1]
    assert call(member.principal, req_tools.SEARCH, query="nothing like it")["requests"] == []


def test_a_feature_without_questions_gets_enhancement_only(login_as, gh):
    admin, member = login_as("admin"), login_as("member")
    gh_tests._configure(admin)
    approve(member, propose(member, req_tools.FILE, **{**DRAFT, "kind": "feature", "open_questions": []}))
    assert json.loads(gh.calls[0].content)["labels"] == ["request", "app:example", "enhancement"]


def test_an_expired_token_says_so(login_as, gh):
    admin, member = login_as("admin"), login_as("member")
    gh_tests._configure(admin)
    gh.status = 401
    out = approve(member, propose(member, req_tools.FILE, **DRAFT))
    assert out["status"] == "uncertain" and "expired or been revoked" in out["error"], out


def test_filing_is_an_outside_effect_offered_only_while_connected(login_as, gh):
    admin, member = login_as("admin"), login_as("member")
    spec = registry.get(req_tools.FILE)
    assert spec is not None and spec.external_effect
    assert not engine.rule_eligible(spec, DRAFT, tainted=False), "no always-allow rule skips the card"
    assert req_tools.FILE not in {s.name for s in registry.for_source("mcp")}
    assert req_tools.FILE not in {s.name for s in registry.for_source("job")}
    assert req_tools.FILE not in {s.name for s in engine.chat_tools(member.principal)}
    gh_tests._configure(admin)
    assert req_tools.FILE in {s.name for s in engine.chat_tools(member.principal)}
