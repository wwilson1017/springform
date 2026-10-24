import json
import threading
from types import SimpleNamespace

import httpx
import pytest

from backend.core import db as core_db, scheduler
from backend.core.requests import github, jobs

REPO = "acme/ops"


@pytest.fixture
def gh(monkeypatch):
    """A fake GitHub: issues created by POST, listed by GET with page/per_page."""
    fake = SimpleNamespace(calls=[], issues={}, status=None)

    def handler(request: httpx.Request) -> httpx.Response:
        fake.calls.append(request)
        assert request.headers["authorization"] == "Bearer tok3n"
        if fake.status:
            return httpx.Response(fake.status, json={"message": "Bad credentials"})
        if request.method == "POST":
            assert request.url.path == f"/repos/{REPO}/issues"
            body = json.loads(request.content)
            number = len(fake.issues) + 1
            fake.issues[number] = {
                "number": number, "html_url": f"https://github.com/{REPO}/issues/{number}", "title": body["title"],
                "body": body["body"], "state": "open", "labels": [{"name": n} for n in body["labels"]],
                "updated_at": "2026-10-24T10:00:00Z",
            }  # fmt: skip
            return httpx.Response(201, json=fake.issues[number])
        params = request.url.params
        assert (params["labels"], params["state"]) == ("request", "all")
        listed = [
            *fake.issues.values(),
            {"number": 99, "title": "a PR", "state": "open", "pull_request": {}, "updated_at": "2026-10-24T10:00:00Z"},
        ]
        page, per_page = int(params["page"]), int(params["per_page"])
        return httpx.Response(200, json=listed[(page - 1) * per_page : page * per_page])

    monkeypatch.setattr(github, "transport", httpx.MockTransport(handler))
    return fake


def _configure(admin) -> None:
    r = admin.put("/api/core/settings", json={"values": {"github.repo": REPO, "github.token": "tok3n"}})
    assert r.status_code == 200, r.text


def test_create_files_a_labelled_issue_and_stores_the_row(login_as, gh):
    admin, member = login_as("admin"), login_as("member")
    _configure(admin)
    r = member.post(
        "/api/core/requests", json={"title": " Show delivery dates ", "app": "example", "description": "On the list."}
    )
    assert r.status_code == 200, r.text
    row = r.json()
    assert row == {
        "id": row["id"], "issue_number": 1, "url": f"https://github.com/{REPO}/issues/1", "state": "open",
        "title": "Show delivery dates", "app": "example", "description": "On the list.",
        "labels": ["request", "app:example"], "requested_by": {"id": member.user["id"], "name": member.user["name"]},
        "created_at": row["created_at"], "updated_at": "2026-10-24T10:00:00Z",
    }  # fmt: skip
    sent = json.loads(gh.calls[0].content)
    assert sent["labels"] == ["request", "app:example"]
    assert sent["body"] == f"**Requested by:** {member.user['name']}\n**App:** Example (`example`)\n\nOn the list."
    assert member.get("/api/core/requests").json() == [row]

    core = member.post("/api/core/requests", json={"title": "Faster sign-in"}).json()
    assert core["app"] == "core" and core["labels"] == ["request", "app:core"]
    assert core_db.one("SELECT app FROM core_requests WHERE id = ?", (core["id"],))["app"] is None
    assert "**App:** Core platform (`core`)" in json.loads(gh.calls[1].content)["body"]


def test_invalid_requests_never_reach_github(login_as, gh):
    admin, member = login_as("admin"), login_as("member")
    _configure(admin)
    assert member.post("/api/core/requests", json={"title": "x", "app": "nope"}).status_code == 422
    assert member.post("/api/core/requests", json={"title": "  "}).status_code == 422
    assert member.post("/api/core/requests", json={"title": "x" * 201}).status_code == 422
    assert member.get("/api/core/requests", params={"state": "maybe"}).status_code == 422
    assert gh.calls == []


def test_not_configured_is_409_and_config_shows_the_warning(login_as, gh):
    admin, member = login_as("admin"), login_as("member")
    r = member.post("/api/core/requests", json={"title": "Anything"})
    assert (r.status_code, r.json()) == (409, {"detail": "github_not_configured"})
    assert admin.post("/api/core/requests/refresh").status_code == 409
    config = member.get("/api/core/requests/config").json()
    assert config["configured"] is False and config["repo"] is None and "passwords" in config["warning_text"]

    admin.put("/api/core/settings", json={"values": {"requests.warning_text": "No customer names, please."}})
    _configure(admin)
    config = member.get("/api/core/requests/config").json()
    assert config == {"configured": True, "warning_text": "No customer names, please.", "repo": REPO}
    assert gh.calls == []


def test_refresh_syncs_state_title_and_updated_at(login_as, gh, monkeypatch):
    admin, member = login_as("admin"), login_as("member")
    _configure(admin)
    first = member.post("/api/core/requests", json={"title": "One"}).json()
    member.post("/api/core/requests", json={"title": "Two"})
    gh.issues[1].update(state="closed", title="One (done)", updated_at="2026-10-25T08:30:00Z")
    monkeypatch.setattr(github, "PER_PAGE", 1)  # one issue per page: exercises pagination
    gh.calls.clear()

    assert member.post("/api/core/requests/refresh").status_code == 403
    r = admin.post("/api/core/requests/refresh")
    assert (r.status_code, r.json()) == (200, {"updated": 1})
    assert len(gh.calls) == 4  # three one-item pages (the PR is dropped), then an empty one

    assert [x["title"] for x in member.get("/api/core/requests").json()] == ["Two"]
    closed = member.get("/api/core/requests", params={"state": "closed"}).json()
    assert [(x["id"], x["title"], x["updated_at"]) for x in closed] == [
        (first["id"], "One (done)", "2026-10-25T08:30:00Z")
    ]
    assert len(member.get("/api/core/requests", params={"state": "all"}).json()) == 2
    assert admin.post("/api/core/requests/refresh").json() == {"updated": 0}
    assert core_db.one("SELECT count(*) AS n FROM core_requests WHERE synced_at IS NULL")["n"] == 0


def test_github_errors_are_502_and_store_nothing(login_as, gh):
    admin, member = login_as("admin"), login_as("member")
    _configure(admin)
    gh.status = 401
    r = member.post("/api/core/requests", json={"title": "Anything"})
    assert (r.status_code, r.json()) == (502, {"detail": "github_error: 401 Bad credentials"})
    assert core_db.one("SELECT count(*) AS n FROM core_requests")["n"] == 0


def test_refresh_job_is_registered_and_idle_until_configured(app, gh):
    assert scheduler.jobs()["core.requests_refresh"].every == 900
    jobs.refresh_board(threading.Event())
    assert gh.calls == []
