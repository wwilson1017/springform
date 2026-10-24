"""Every test runs on a real temporary SQLite database; nothing in the data layer is mocked."""

import contextlib
import itertools

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.core import clock, db as core_db
from backend.core.auth import bootstrap, service as auth_service
from backend.core.auth.deps import User

PASSWORD = "correct-horse-battery"
_ENV = (
    "PREVIEW_MODE", "ENCRYPTION_KEY", "SECRET_KEY", "PUBLIC_URL", "TRUST_PROXY", "SPRINGFORM_REQUIRE_SQLITE",
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "RESEND_API_KEY",
)
_counter = itertools.count(1)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    for key in _ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(auth_service, "BCRYPT_ROUNDS", 4)
    clock.freeze(None)
    yield
    clock.freeze(None)
    core_db.set_commit_nudge(None)
    core_db.close()


def _http_clients() -> list[tuple[type, str, bool]]:
    """(class, method, is_async) for every HTTP client the code reaches: httpx, httpx2 (the AI SDKs)
    and requests (pywebpush). A client whose module is not installed is left out."""
    clients = [(httpx.Client, "send", False), (httpx.AsyncClient, "send", True)]
    with contextlib.suppress(ImportError):
        import httpx2

        clients += [(httpx2.Client, "send", False), (httpx2.AsyncClient, "send", True)]
    with contextlib.suppress(ImportError):
        import requests.sessions

        clients.append((requests.sessions.Session, "request", False))
    return clients


_HTTP_CLIENTS = _http_clients()


def _refuse_inside_transaction(original, is_async: bool):
    def guard():
        if core_db.in_transaction():
            raise AssertionError("network call inside transaction()")

    def call(self, *args, **kwargs):
        guard()
        return original(self, *args, **kwargs)

    async def acall(self, *args, **kwargs):
        guard()
        return await original(self, *args, **kwargs)

    return acall if is_async else call


@pytest.fixture(autouse=True)
def _no_network_inside_transaction(monkeypatch):
    """The rule "no network call inside transaction()", enforced for the whole suite."""
    for cls, method, is_async in _HTTP_CLIENTS:
        monkeypatch.setattr(cls, method, _refuse_inside_transaction(getattr(cls, method), is_async))


@pytest.fixture
def db(tmp_path):
    """A migrated database (core + installed apps) in this test's data dir."""
    core_db.init(tmp_path / "data")
    core_db.migrate()
    yield core_db
    core_db.close()


@pytest.fixture
def freeze():
    """freeze("2026-11-02T09:00:00Z") pins core.clock; unpinned after the test."""
    yield clock.freeze
    clock.freeze(None)


@pytest.fixture
def app(db):
    from backend.main import create_app

    return create_app()


def make_client(app, **headers) -> TestClient:
    """A browser-like client: same-origin fetch metadata, cookies kept, lifespan not run."""
    return TestClient(app, headers={"Sec-Fetch-Site": "same-origin", **headers})


@pytest.fixture
def client(app):
    return make_client(app)


@pytest.fixture
def make_user(db):
    """make_user(role) -> User, created directly (no HTTP)."""

    def _make(role: str = "member", email: str | None = None, password: str | None = PASSWORD) -> User:
        n = next(_counter)
        with core_db.transaction() as conn:
            row = auth_service.create_user_in(conn, email or f"{role}{n}@example.com", f"{role.title()} {n}", role, password)
        return User.from_row(row)

    return _make


@pytest.fixture
def login_as(app):
    """login_as(role, on=app) -> a TestClient signed in as a new user of that role; `.user` holds the
    /api/me shape and `.principal` the User. The first account goes through the real setup-token
    path (an admin, as on a fresh install); later ones are created and sign in via /api/auth/login."""

    def _login(role: str = "member", email: str | None = None, on=None) -> TestClient:
        n = next(_counter)
        email = email or f"{role}{n}@example.com"
        client = make_client(on or app)
        token = bootstrap.ensure_setup_token()
        if token is not None and role != "admin":
            _login("admin", on=on)  # finish setup first, as a real install would
            token = None
        if token is not None:
            r = client.post("/api/auth/setup", json={"token": token, "email": email, "name": f"Admin {n}", "password": PASSWORD})
        else:
            with core_db.transaction() as conn:
                auth_service.create_user_in(conn, email, f"{role.title()} {n}", role, PASSWORD)
            r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        client.user = r.json()["user"]
        client.principal = User.from_row(auth_service.get_user(client.user["id"]))
        return client

    return _login
