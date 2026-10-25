"""CSV writer, report CSV visibility, and the admin business-data export ZIP."""

import csv
import io
import json
import zipfile

import pytest

from backend.core import clock, db as core_db
from backend.core.export import csv_export, policy
from backend.core.reports import registry as reports
from backend.core.reports.registry import Report
from backend.tests.conftest import make_client

# ── The CSV writer ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("value, expected", [
    ("=1+1", "'=1+1"), ("+1 615 555 0100", "'+1 615 555 0100"), ("-5", "'-5"), ("@SUM(A1)", "'@SUM(A1)"),
    ("\tx", "'\tx"), ("\rx", "'\rx"), ("a=b", "a=b"), ("", ""), (-5, -5), (3.5, 3.5), (None, None),
    ({"a": 1}, '{"a": 1}'), (["=x"], '["=x"]'),
])
def test_cell_guard(value, expected):
    assert csv_export._cell(value) == expected


def test_stream_csv_is_a_utf8_bom_attachment():
    """Its own small app: on create_app() a built frontend's SPA catch-all would shadow the route."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/test-csv")
    def _csv():
        return csv_export.stream_csv(["name", "=note"], [["Zoë", "=HYPERLINK(1)"], ["Bob", None]], "people list.csv")

    r = TestClient(app).get("/test-csv")
    assert r.headers["content-disposition"] == 'attachment; filename="people_list.csv"'
    assert r.headers["content-type"].startswith("text/csv")
    assert r.content.startswith("﻿".encode())
    assert list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")))) == [
        ["name", "'=note"], ["Zoë", "'=HYPERLINK(1)"], ["Bob", ""],
    ]


# ── Report CSV ──────────────────────────────────────────────────────────────────────


def test_report_csv_respects_admin_only_and_app_roles(app, login_as):
    echo = lambda params, user: (["param", "value"], sorted(params.items()))  # noqa: E731
    reports.register(Report(key="example.secret", label="Secret", app="example", run=echo, admin_only=True))
    reports.register(Report(key="example.admins", label="Admins", app="example", run=echo, roles=("admin",)))
    params = {"type": "object", "properties": {
        "since": {"type": "string", "format": "date"}, "q": {"type": "string"}, "limit": {"type": "integer", "default": 10},
    }}
    reports.register(Report(key="example.echo", label="Echo", app="example", run=echo, roles=("admin", "member"), params=params))
    admin, member = login_as("admin"), login_as("member")
    member.post("/api/example/widgets", json={"name": "Cog", "color": "teal"})

    r = member.get("/api/core/reports/example.widgets_by_color/csv")
    assert r.status_code == 200 and r.content.decode("utf-8-sig").splitlines() == ["color,widgets", "teal,1"]
    assert r.headers["content-disposition"] == 'attachment; filename="example.widgets_by_color.csv"'
    assert member.get("/api/core/reports/example.echo/csv?since=2026-01-01&q==x").content.decode("utf-8-sig").splitlines() == [
        "param,value", "limit,10", "q,'=x", "since,2026-01-01",
    ]  # params parsed like the JSON route: the default applied
    assert member.get("/api/core/reports/example.echo/csv?limit=3").content.decode("utf-8-sig").splitlines() == [
        "param,value", "limit,3",
    ]
    for bad, detail in (("since=2026-02-30", "since: expected a date (YYYY-MM-DD)"),
                        ("limit=many", "limit: expected an integer"), ("format=xlsx", "unknown param: format")):
        r = member.get(f"/api/core/reports/example.echo/csv?{bad}")
        assert (r.status_code, r.json()) == (422, {"detail": detail}), bad
    assert member.get("/api/core/reports/example.secret/csv").json() == {"detail": "admin_only"}
    assert member.get("/api/core/reports/example.admins/csv").status_code == 403
    assert member.get("/api/core/reports/example.nope/csv").status_code == 404
    assert admin.get("/api/core/reports/example.secret/csv").status_code == 200
    assert admin.get("/api/core/reports/example.admins/csv").status_code == 200
    assert make_client(app).get("/api/core/reports/example.echo/csv").status_code == 401


# ── The export ZIP ──────────────────────────────────────────────────────────────────


def _zip(client) -> zipfile.ZipFile:
    r = client.get("/api/core/export")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"].startswith('attachment; filename="springform-export-')
    return zipfile.ZipFile(io.BytesIO(r.content))


def _csv(z: zipfile.ZipFile, table: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(z.read(f"{table}.csv").decode("utf-8-sig"))))


def _header(z: zipfile.ZipFile, table: str) -> list[str]:
    return next(csv.reader(io.StringIO(z.read(f"{table}.csv").decode("utf-8-sig"))))


PINNED = {  # the core tables on master today, and exactly the columns they export
    "core_users": ["id", "email", "name", "role"],
    "core_people": ["id", "name", "given_name", "family_name", "email", "phone", "title", "source", "status", "tags",
                    "notes", "owner_user_id", "archived_at", "merged_into_id", "created_at", "updated_at"],
    "core_organizations": ["id", "name", "domain", "website", "industry", "email", "phone", "notes", "source", "status",
                           "tags", "owner_user_id", "archived_at", "merged_into_id", "created_at", "updated_at"],
    "core_person_organizations": ["id", "person_id", "organization_id", "role", "is_primary", "started_on", "ended_on", "created_at"],
    "core_addresses": ["id", "owner_type", "owner_id", "kind", "line1", "line2", "city", "region", "postal_code", "country",
                       "is_primary", "created_at", "updated_at"],
    "core_contact_channels": ["id", "owner_type", "owner_id", "kind", "value", "label", "is_primary", "created_at", "updated_at"],
    "core_timeline": ["id", "entity_type", "entity_id", "kind", "body", "author_user_id", "created_at", "updated_at", "archived_at"],
    "core_files": ["id", "entity_type", "entity_id", "timeline_id", "filename", "mime_type", "byte_size", "sha256",
                   "uploaded_by", "created_at"],
    "example_widgets": ["id", "name", "color", "owner_user_id", "person_id", "is_private", "created_at", "updated_at"],
}


def test_export_pins_columns_omits_secrets_and_carries_a_manifest(app, login_as, freeze):
    freeze("2026-11-02T09:00:00Z")
    admin = login_as("admin")
    now = clock.now_iso()
    with core_db.transaction() as conn:
        conn.execute("INSERT INTO core_people (name, notes, created_at, updated_at) VALUES ('Ada', '=cmd|calc', ?, ?)", (now, now))
        conn.execute(
            "INSERT INTO core_contact_channels (owner_type, owner_id, kind, value, created_at, updated_at) VALUES ('person', 1, 'phone', '+1 615', ?, ?)",
            (now, now),
        )
        conn.execute("INSERT INTO core_settings (key, value, is_secret, updated_at) VALUES ('ai.key', 'enc:v1:zzz', 1, ?)", (now,))
    z = _zip(admin)

    names = set(z.namelist())
    assert {f"{t}.csv" for t in PINNED} | {"manifest.json"} <= names
    for table, columns in PINNED.items():
        assert _header(z, table) == columns, table
    for never in ("core_settings", "core_totp", "core_trusted_devices", "core_login_tokens", "core_login_attempts",
                  "core_outbox", "core_backups", "core_sheet_cache", "core_job_runs", "core_change_log"):
        assert f"{never}.csv" not in names
    everything = b"".join(z.read(n) for n in names)
    assert b"password_hash" not in everything and b"$2b$" not in everything and b"enc:v1:" not in everything
    assert _csv(z, "core_people")[0]["notes"] == "'=cmd|calc"
    assert _csv(z, "core_contact_channels")[0]["value"] == "'+1 615"
    assert [u["role"] for u in _csv(z, "core_users")] == ["system", "admin"]

    manifest = json.loads(z.read("manifest.json"))
    assert (manifest["version"], manifest["created_at"], manifest["exported_by"]) == (core_db.VERSION, "2026-11-02T09:00:00Z", admin.user["id"])
    counts = {t["name"]: t["rows"] for t in manifest["tables"]}
    assert counts["core_people"] == 1 and counts["core_users"] == 2 and counts["example_widgets"] == 0
    assert set(counts) == {n.removesuffix(".csv") for n in names if n.endswith(".csv")}


def test_export_rows_follow_the_screen_a_members_private_widget_and_its_notes_are_absent(app, login_as):
    admin, member = login_as("admin"), login_as("member")
    private = member.post("/api/example/widgets", json={"name": "Secret gear", "is_private": True}).json()
    public = member.post("/api/example/widgets", json={"name": "Sprocket"}).json()
    mine = admin.post("/api/example/widgets", json={"name": "Admin's own", "is_private": True}).json()
    for client, widget, body in ((member, private, "private note"), (member, public, "public note"), (admin, mine, "admin note")):
        r = client.post("/api/core/timeline", json={"entity_type": "example.widget", "entity_id": widget["id"], "body": body})
        assert r.status_code == 200, r.text
    admin.patch(f"/api/example/widgets/{mine['id']}", json={"color": "red"})  # a field_change row: never exported

    z = _zip(admin)
    assert sorted(w["name"] for w in _csv(z, "example_widgets")) == ["Admin's own", "Sprocket"]
    timeline = _csv(z, "core_timeline")
    assert sorted(t["body"] for t in timeline) == ["admin note", "public note"]
    assert {t["kind"] for t in timeline} == {"note"}
    counts = {t["name"]: t["rows"] for t in json.loads(z.read("manifest.json"))["tables"]}
    assert (counts["example_widgets"], counts["core_timeline"]) == (2, 2)

    preview = admin.get("/api/core/export/preview").json()["tables"]
    by_name = {t["name"]: t for t in preview}
    assert by_name["example_widgets"] == {"name": "example_widgets", "columns": PINNED["example_widgets"], "estimated_rows": 3}
    assert by_name["core_timeline"]["estimated_rows"] == 3  # notes only, before row checks
    assert member.get("/api/core/export").status_code == 403
    assert member.get("/api/core/export/preview").status_code == 403


def test_sibling_tables_follow_the_screen_reminders_and_field_values(app, login_as):
    """Reminders and field values come from other workstreams; minimal stand-ins are created only
    when the real tables are absent, so this holds before and after they merge."""
    admin, member = login_as("admin"), login_as("member")
    private = member.post("/api/example/widgets", json={"name": "Secret gear", "is_private": True}).json()["id"]
    public = member.post("/api/example/widgets", json={"name": "Sprocket"}).json()["id"]
    a, m, now = admin.user["id"], member.user["id"], clock.now_iso()
    with core_db.transaction() as conn:
        for ddl in (
            """CREATE TABLE IF NOT EXISTS core_reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_user_id INTEGER,
                   entity_type TEXT, entity_id INTEGER, title TEXT, due_at TEXT, created_at TEXT, updated_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS core_field_definitions (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT,
                   key TEXT, label TEXT, type TEXT, created_at TEXT, updated_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS core_field_values (entity_type TEXT, entity_id INTEGER, definition_id INTEGER,
                   value TEXT, updated_at TEXT)""",
        ):
            conn.execute(ddl)
        conn.executemany(
            "INSERT INTO core_reminders (owner_user_id, entity_type, entity_id, title, due_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(a, None, None, "admin's own", now, now, now), (m, None, None, "member's own", now, now, now),
             (m, "example.widget", private, "on private", now, now, now), (m, "example.widget", public, "on public", now, now, now)],
        )
        definition = conn.execute(
            "INSERT INTO core_field_definitions (entity_type, key, label, type, created_at, updated_at) VALUES ('example.widget', 'size', 'Size', 'text', ?, ?)",
            (now, now),
        ).lastrowid
        conn.executemany(
            "INSERT INTO core_field_values (entity_type, entity_id, definition_id, value, updated_at) VALUES ('example.widget', ?, ?, ?, ?)",
            [(private, definition, '"secret"', now), (public, definition, '"large"', now)],
        )
    z = _zip(admin)
    assert sorted(r["title"] for r in _csv(z, "core_reminders")) == ["admin's own", "on public"]
    assert [v["value"] for v in _csv(z, "core_field_values")] == ['"large"']
    assert [d["key"] for d in _csv(z, "core_field_definitions")] == ["size"]


def test_missing_tables_are_skipped_and_missing_columns_dropped(app, login_as, monkeypatch):
    admin = login_as("admin")
    monkeypatch.setitem(policy.CORE_EXPORT, "core_not_yet", {"entity": None, "columns": ["id"]})
    monkeypatch.setitem(policy.CORE_EXPORT, "core_users", {"entity": None, "columns": ["id", "nickname", "email"]})
    z = _zip(admin)
    assert "core_not_yet.csv" not in z.namelist()
    assert _header(z, "core_users") == ["id", "email"]


def test_policy_check_refuses_never_exported_tables_and_columns():
    policy.check(policy.CORE_EXPORT)
    with pytest.raises(ValueError, match="core_totp"):
        policy.check({"core_totp": {"entity": None, "columns": ["user_id"]}})
    with pytest.raises(ValueError, match="core_agent_messages"):
        policy.check({"core_agent_messages": {"entity": None, "columns": ["id"]}})
    with pytest.raises(ValueError, match="password_hash"):
        policy.check({"core_users": {"entity": None, "columns": ["id", "password_hash"]}})
