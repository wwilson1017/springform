"""Security headers cover the whole response stack, preserving route overrides."""

import asyncio

import pytest
from fastapi.responses import Response
from fastapi.testclient import TestClient

from backend.core import security_headers
from backend.core.auth.deps import COOKIE
from backend.tests.conftest import make_client

EXPECTED = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "SAMEORIGIN",
    "content-security-policy": "frame-ancestors 'self'",
    "referrer-policy": "strict-origin-when-cross-origin",
}


def _assert_headers(response, scheme="http", overrides=None):
    expected = dict(EXPECTED)
    if scheme == "https":
        expected["strict-transport-security"] = "max-age=31536000"
    expected.update(overrides or {})
    for name, value in expected.items():
        assert response.headers.get_list(name) == [value]
    if "strict-transport-security" not in expected:
        assert "strict-transport-security" not in response.headers


@pytest.fixture
def empty_frontend_app(db, tmp_path, monkeypatch):
    from backend import main

    monkeypatch.setattr(main, "FRONTEND_DIST", tmp_path)
    return main.create_app()


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_api_headers(app, scheme):
    client = TestClient(app, base_url=f"{scheme}://testserver", headers={"Sec-Fetch-Site": "same-origin"})
    response = client.get("/api/health")
    assert response.status_code == 200
    _assert_headers(response, scheme)


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_spa_headers(db, tmp_path, monkeypatch, scheme):
    from backend import main

    html = "<!doctype html><title>Test SPA</title>"
    (tmp_path / "index.html").write_text(html)
    monkeypatch.setattr(main, "FRONTEND_DIST", tmp_path)
    client = TestClient(main.create_app(), base_url=f"{scheme}://testserver")
    for path in ("/", "/contacts"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.text == html
        _assert_headers(response, scheme)


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_file_download_headers(login_as, scheme):
    member = login_as("member")
    member.base_url = f"{scheme}://testserver"
    widget = member.post("/api/example/widgets", json={"name": "Gear"})
    assert widget.status_code == 200, widget.text
    data = b"hello world\n"
    upload = member.post(
        "/api/core/files",
        data={"entity_type": "example.widget", "entity_id": str(widget.json()["id"])},
        files={"file": ("notes.txt", data, "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    response = member.get(f"/api/core/files/{upload.json()['id']}/download")
    assert response.status_code == 200
    assert response.content == data
    _assert_headers(response, scheme)


@pytest.mark.parametrize("name,value", [
    ("X-Frame-Options", "DENY"),
    ("X-Content-Type-Options", "custom"),
    ("Content-Security-Policy", "frame-ancestors 'none'"),
    ("Referrer-Policy", "no-referrer"),
    ("Strict-Transport-Security", "max-age=60"),
])
@pytest.mark.parametrize("scheme", ["http", "https"])
def test_route_header_wins(empty_frontend_app, name, value, scheme):
    @empty_frontend_app.get("/api/test-own-header")
    def own_header():
        return Response(headers={name: value})

    client = TestClient(empty_frontend_app, base_url=f"{scheme}://testserver")
    response = client.get("/api/test-own-header")
    assert response.status_code == 200
    _assert_headers(response, scheme, {name.lower(): value})


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_unhandled_exception_headers(empty_frontend_app, scheme):
    @empty_frontend_app.get("/api/test-boom")
    def boom():
        raise RuntimeError("test failure")

    client = TestClient(empty_frontend_app, base_url=f"{scheme}://testserver", raise_server_exceptions=False)
    response = client.get("/api/test-boom")
    assert response.status_code == 500
    _assert_headers(response, scheme)


def test_csrf_refusal_headers(login_as):
    member = login_as("member")
    cross = make_client(member.app, **{"Sec-Fetch-Site": "cross-site"})
    cross.cookies.set(COOKIE, member.cookies[COOKIE])
    response = cross.post("/api/example/widgets", json={"name": "Gear"})
    assert response.status_code == 403
    assert response.json() == {"detail": "csrf_refused"}
    _assert_headers(response)


@pytest.mark.parametrize("scope_type", ["lifespan", "websocket"])
def test_non_http_passes_through(scope_type):
    scope = {"type": scope_type}
    incoming = {"type": f"{scope_type}.disconnect"}
    outgoing = {"type": f"{scope_type}.close"}
    sent = []

    async def receive():
        return incoming

    async def send(message):
        sent.append(message)

    async def asgi(actual_scope, actual_receive, actual_send):
        assert actual_scope is scope
        assert actual_receive is receive
        assert actual_send is send
        assert await actual_receive() is incoming
        await actual_send(outgoing)

    asyncio.run(security_headers._wrap(asgi)(scope, receive, send))
    assert sent == [outgoing]
