"""Every core route that answers with a response model, called through the real app as admin and as
member. Each answers with exactly the key paths it answered with before it had a model:
`fixtures/response_shapes.json` was recorded from the untyped routes, and a change that reshapes a
route on purpose updates it. The models forbid extra keys, so a key a service adds without adding
it to the model answers 500 here instead of silently vanishing from the response."""

import itertools
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.core import clock, db as core_db
from backend.core.agent import providers, registry as tool_registry
from backend.core.agent.providers import fake
from backend.core.requests import github
from backend.core.sheets import google, startup as sheets_startup
from backend.tests.fixtures import mcp_stub

SHAPES = Path(__file__).parent / "fixtures" / "response_shapes.json"
OK = (200, 201, 202)


def shape(body, prefix: str = "") -> list[str]:
    """Every key path in a JSON body, sorted: `items[].owner.id`."""
    paths: set[str] = set()
    if isinstance(body, dict):
        for key, value in body.items():
            paths.add(prefix + key)
            paths.update(shape(value, f"{prefix}{key}."))
    elif isinstance(body, list):
        for item in body:
            paths.update(shape(item, prefix.removesuffix(".") + "[]."))
    return sorted(paths)


class Recorder(dict):
    """hit(client, method, route, note, json=, params=, **path_params) -> body; keeps each response
    under "<METHOD> <route> <role> [note]"."""

    def __call__(self, who, method: str, route: str, note: str = "", *, json=None, params=None, **path):
        r = who.request(method, route.format(**path), json=json, params=params)
        label = " ".join(filter(None, (method, route, who.user["role"], note)))
        assert label not in self, label
        assert r.status_code in OK, (label, r.status_code, r.text)
        self[label] = r
        return r.json()


def _github() -> httpx.MockTransport:
    numbers = itertools.count(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body, n = json.loads(request.content), next(numbers)
            return httpx.Response(201, json={
                "number": n, "html_url": f"https://github.com/acme/ops/issues/{n}", "title": body["title"],
                "state": "open", "labels": [{"name": label} for label in body["labels"]], "updated_at": clock.now_iso(),
            })  # fmt: skip
        return httpx.Response(200, json=[])

    return httpx.MockTransport(handler)


def _service_account() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return json.dumps({"type": "service_account", "client_email": "sheets@demo.iam.gserviceaccount.com", "private_key": pem.decode()})


async def _started(name: str) -> bool:
    return True


def exercise(app, login_as, monkeypatch) -> dict[str, httpx.Response]:
    """Call every typed route once per role that may call it, in an order that gives each body
    something to show (links, channels, tool calls, change-log rows)."""
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    monkeypatch.setenv("MCP_ALLOW_PRIVATE", "1")
    monkeypatch.setattr(github, "transport", _github())
    sheet = SimpleNamespace(read=lambda spreadsheet_id, a1: [["name", "color"], ["Sprocket", "teal"], ["Gear"]])
    monkeypatch.setattr(google, "make_client", lambda info: sheet)
    monkeypatch.setattr(providers, "make", lambda provider, key, model: fake.FakeProvider(model))
    app.state.scheduler = SimpleNamespace(jobs={"core.backup": None}, run_now=_started)
    fake.reset()
    sheets_startup.on_startup()
    admin, member = login_as("admin"), login_as("member")
    both, hit = (admin, member), Recorder()

    # ── Platform: health, apps, workspace, settings, jobs ──
    hit(member, "GET", "/api/health")
    for c in both:
        hit(c, "GET", "/api/core/apps")
        hit(c, "GET", "/api/core/workspace")
    hit(admin, "GET", "/api/core/settings")
    hit(admin, "PUT", "/api/core/settings", json={
        "values": {"workspace.name": "Acme Bakery", "github.repo": "acme/ops", "github.token": "tok3n"},
    })  # fmt: skip
    hit(admin, "DELETE", "/api/core/settings/{key}", key="workspace.name")
    hit(admin, "PATCH", "/api/core/apps/{slug}", slug="example", json={"hidden": False})
    slugs = [a["slug"] for a in admin.get("/api/core/apps").json()]
    hit(admin, "PUT", "/api/core/apps/order", json={"slugs": slugs[::-1]})
    with core_db.transaction() as conn:
        now = clock.now_iso()
        conn.execute(
            """INSERT INTO core_job_runs (job, app, trigger, status, started_at, finished_at)
               VALUES ('core.backup', 'core', 'manual', 'ok', ?, ?)""",
            (now, now),
        )
        conn.execute(
            """INSERT INTO core_outbox (hook, payload, created_at, available_at, attempts, last_error, dead_at)
               VALUES ('core.example', '{}', ?, ?, 5, 'gave up', ?)""",
            (now, now, now),
        )
    hit(admin, "GET", "/api/core/jobs")
    hit(admin, "GET", "/api/core/jobs/runs")
    hit(admin, "GET", "/api/core/jobs/outbox/dead")
    hit(admin, "POST", "/api/core/jobs/{name}/run", name="core.backup")

    # ── Guide and requests ──
    for c in both:
        slug = hit(c, "GET", "/api/core/guide")[0]["slug"]
        hit(c, "GET", "/api/core/guide/search", params={"q": "backup"})
        hit(c, "GET", "/api/core/guide/{slug}", slug=slug)
        hit(c, "POST", "/api/core/requests", json={"title": f"Request from {c.user['role']}", "description": "Please."})
        hit(c, "GET", "/api/core/requests")
        hit(c, "GET", "/api/core/requests/config")
    hit(admin, "POST", "/api/core/requests/refresh")

    # ── Backups and sheets ──
    run = hit(admin, "POST", "/api/core/backups/run")
    hit(admin, "GET", "/api/core/backups")
    hit(admin, "POST", "/api/core/backups/key")
    hit(admin, "GET", "/api/core/backups/{stamp}/manifest", stamp=run["snapshot"].split(".")[0])
    hit(admin, "PUT", "/api/core/sheets/credentials", json={"service_account_json": _service_account()})
    hit(admin, "GET", "/api/core/sheets/credentials")
    sheet_id = hit(admin, "GET", "/api/core/sheets")[0]["id"]
    hit(admin, "PATCH", "/api/core/sheets/{sheet_id}", sheet_id=sheet_id, json={"spreadsheet_id": "abc123", "range": "A1:B"})
    hit(admin, "POST", "/api/core/sheets/{sheet_id}/refresh", sheet_id=sheet_id)
    hit(admin, "GET", "/api/core/sheets/{sheet_id}/preview", sheet_id=sheet_id)

    # ── Contacts ──
    people = {}
    for c in both:
        role = c.user["role"]
        pid = hit(c, "POST", "/api/core/contacts/people", json={"name": f"Pat {role}", "email": f"pat.{role}@example.com", "tags": ["vip"]})["id"]
        oid = hit(c, "POST", "/api/core/contacts/organizations", json={"name": f"Acme {role}", "domain": f"{role}.example.com"})["id"]
        people[role] = pid
        link = {"person_id": pid, "organization_id": oid, "role": "Owner"}
        hit(c, "POST", "/api/core/contacts/links", json={**link, "is_primary": True, "started_on": "2026-01-05"})
        hit(c, "PATCH", "/api/core/contacts/links", json={**link, "new_role": "Founder"})
        channel = hit(c, "POST", "/api/core/contacts/channels", json={"owner_type": "person", "owner_id": pid, "kind": "url", "value": "https://example.com/pat"})
        hit(c, "PATCH", "/api/core/contacts/channels/{part_id}", part_id=channel["id"], json={"label": "Site"})
        address = hit(c, "POST", "/api/core/contacts/addresses", json={"owner_type": "organization", "owner_id": oid, "kind": "office", "line1": "1 Main St", "city": "Springfield"})
        hit(c, "PATCH", "/api/core/contacts/addresses/{part_id}", part_id=address["id"], json={"postal_code": "00000"})
        hit(c, "PATCH", "/api/core/contacts/people/{record_id}", record_id=pid, json={"title": "Baker"})
        hit(c, "PATCH", "/api/core/contacts/organizations/{record_id}", record_id=oid, json={"industry": "Food"})
        hit(c, "GET", "/api/core/contacts/people/{record_id}", record_id=pid)
        hit(c, "GET", "/api/core/contacts/organizations/{record_id}", record_id=oid)
        hit(c, "GET", "/api/core/contacts/people")
        hit(c, "GET", "/api/core/contacts/organizations")
        hit(c, "GET", "/api/core/contacts/search", params={"q": "pat"})
        twin = hit(c, "POST", "/api/core/contacts/people", "twin", json={"name": f"Pat {role}"})["id"]
        org_twin = hit(c, "POST", "/api/core/contacts/organizations", "twin", json={"name": f"Acme {role} Two", "domain": f"{role}.example.com"})["id"]
        hit(c, "GET", "/api/core/contacts/people/duplicates")
        hit(c, "GET", "/api/core/contacts/organizations/duplicates")
        hit(c, "POST", "/api/core/contacts/people/merge", json={"target_id": pid, "source_id": twin})
        hit(c, "POST", "/api/core/contacts/organizations/merge", json={"target_id": oid, "source_id": org_twin})
        hit(c, "GET", "/api/core/contacts/people/{record_id}", "merged", record_id=twin)
        hit(c, "GET", "/api/core/contacts/organizations/{record_id}", "merged", record_id=org_twin)
        for kind, record_id in (("people", pid), ("organizations", oid)):
            hit(c, "DELETE", f"/api/core/contacts/{kind}/{{record_id}}", record_id=record_id)
            hit(c, "POST", f"/api/core/contacts/{kind}/{{record_id}}/restore", record_id=record_id)
        hit(c, "DELETE", "/api/core/contacts/channels/{part_id}", part_id=channel["id"])
        hit(c, "DELETE", "/api/core/contacts/addresses/{part_id}", part_id=address["id"])
        hit(c, "DELETE", "/api/core/contacts/links", json={**link, "role": "Founder"})

    # ── Records: timeline, fields, views, reports, notifications, change log ──
    for c, other in ((admin, member), (member, admin)):
        mention = f"@[{other.user['name']}](user:{other.user['id']})"
        target = {"entity_type": "core.person", "entity_id": people["admin"]}
        hit(c, "POST", "/api/core/timeline", json={**target, "body": f"Call back {mention}"})
        hit(c, "GET", "/api/core/timeline", params=target)
        hit(c, "GET", "/api/core/timeline/mentionable")
    definition = hit(admin, "POST", "/api/core/fields/definitions", json={
        "entity_type": "core.person", "label": "Shoe size", "type": "select", "options": ["S", "M"],
    })  # fmt: skip
    hit(admin, "PATCH", "/api/core/fields/definitions/{definition_id}", definition_id=definition["id"], json={"label": "Size"})
    for c in both:
        hit(c, "GET", "/api/core/fields/definitions", params={"entity_type": "core.person"})
        view = hit(c, "POST", "/api/core/views", json={"surface": "core.people", "name": f"Mine {c.user['role']}", "payload": {"q": "pat", "sort": ["name"]}})
        hit(c, "PATCH", "/api/core/views/{view_id}", view_id=view["id"], json={"version": 1, "name": "Renamed"})
        hit(c, "POST", "/api/core/views/{view_id}/share", view_id=view["id"], json={"is_shared": True})
        hit(c, "GET", "/api/core/views", params={"surface": "core.people"})
        key = hit(c, "GET", "/api/core/reports")[0]["key"]
        hit(c, "GET", "/api/core/reports/{key}", key=key)
        hit(c, "GET", "/api/core/notifications/unread-count")
        hit(c, "POST", "/api/core/notifications/read-all")
        hit(c, "GET", "/api/core/notifications/push/public-key")
        endpoint = f"https://push.example.com/{c.user['role']}"
        hit(c, "POST", "/api/core/notifications/push/subscribe", json={"endpoint": endpoint, "keys": {"p256dh": "k", "auth": "a"}})
        hit(c, "DELETE", "/api/core/notifications/push/subscribe", json={"endpoint": endpoint})
        hit(c, "GET", "/api/core/changelog")

    # ── Whisk ──
    for c in both:
        hit(c, "GET", "/api/agent/status")
        hit(c, "GET", "/api/agent/agents")
    hit(admin, "PATCH", "/api/agent/agents/{slug}", slug="whisk", json={"personality": "Be brief."})
    hit(admin, "GET", "/api/agent/providers")
    hit(admin, "PUT", "/api/agent/providers/{provider}", provider="openai", json={"api_key": "sk-test"})
    hit(admin, "POST", "/api/agent/providers/{provider}/test", provider="openai")
    for c, decision in ((admin, "approve"), (member, "deny")):
        cid = hit(c, "POST", "/api/agent/conversations", json={})["id"]
        hit(c, "PATCH", "/api/agent/conversations/{conversation_id}", conversation_id=cid, json={"title": "Widgets"})
        fake.script({"tool": "example_create_widget", "args": {"name": f"Gizmo {decision}"}}, "I'd like to create that widget.")
        stream = c.post("/api/agent/chat", json={"conversation_id": cid, "message": "make a widget"}).text
        events = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith("data: ")]
        run_id = next(e["tool_run_id"] for e in events if e["type"] == "confirm")
        hit(c, "GET", "/api/agent/conversations/{conversation_id}", "pending", conversation_id=cid)
        hit(c, "POST", "/api/agent/confirm", decision, json={"tool_run_id": run_id, "decision": decision})
        hit(c, "POST", "/api/agent/confirm", "again", json={"tool_run_id": run_id, "decision": decision})
        hit(c, "GET", "/api/agent/conversations/{conversation_id}", "resolved", conversation_id=cid)
        hit(c, "GET", "/api/agent/conversations")
        hit(c, "DELETE", "/api/agent/conversations/{conversation_id}", conversation_id=cid)

    # ── MCP: inbound links and outbound servers ──
    for c in both:
        hit(c, "POST", "/api/core/mcp/links", json={"label": f"Laptop {c.user['role']}"})
        hit(c, "GET", "/api/core/mcp/links")
    hit(admin, "GET", "/api/core/mcp/links", "all", params={"all": "true"})
    url, _ = mcp_stub.serve("stub-token")
    before = tool_registry.current()
    try:
        server_id = hit(admin, "POST", "/api/core/mcp/servers", json={"name": "Stub", "url": url, "token": "stub-token", "prefix": "stub"})["id"]
        hit(admin, "GET", "/api/core/mcp/servers")
        hit(admin, "PATCH", "/api/core/mcp/servers/{server_id}", server_id=server_id, json={"name": "Stub todos"})
        hit(admin, "POST", "/api/core/mcp/servers/{server_id}/refresh", server_id=server_id)
        hit(admin, "POST", "/api/core/mcp/servers/{server_id}/test", server_id=server_id)
    finally:
        tool_registry.set_current(before)
        fake.reset()

    # Admin-only routers refuse members before any model is involved.
    for method, path in (
        ("GET", "/api/core/settings"), ("GET", "/api/core/jobs"), ("GET", "/api/core/backups"), ("GET", "/api/core/sheets"),
        ("GET", "/api/agent/providers"), ("GET", "/api/core/mcp/servers"), ("POST", "/api/core/requests/refresh"),
    ):  # fmt: skip
        assert member.request(method, path).status_code == 403, path
    return hit


def test_typed_routes_answer_with_their_recorded_keys(app, login_as, monkeypatch, freeze):
    freeze("2026-11-02T15:00:00Z")
    seen = {label: shape(r.json()) for label, r in exercise(app, login_as, monkeypatch).items()}
    assert seen == json.loads(SHAPES.read_text())
