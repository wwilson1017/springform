"""The API docs and the OpenAPI schema are for signed-in users only (#28)."""

import pytest

import backend.main as main
from backend.tests.conftest import make_client

PATHS = ["/openapi.json", "/docs", "/redoc"]


@pytest.fixture
def app(db, tmp_path, monkeypatch):
    """The app with a built SPA, so a signed-out request proves it is not answered by index.html."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>spa</html>")
    monkeypatch.setattr(main, "FRONTEND_DIST", dist)
    return main.create_app()


@pytest.mark.parametrize("path", PATHS)
def test_signed_out_gets_401_not_the_spa(app, path):
    r = make_client(app).get(path)
    assert r.status_code == 401
    assert r.json()["detail"] == "not_authenticated"


def test_signed_in_gets_the_docs_and_the_schema(login_as):
    client = login_as("member")
    for path in PATHS:
        assert client.get(path).status_code == 200, path

    schema = client.get("/openapi.json").json()
    assert "/api/health" in schema["paths"]
    assert not set(PATHS) & set(schema["paths"])  # the docs routes stay out of the schema
    assert "/openapi.json" in client.get("/docs").text
    assert "/openapi.json" in client.get("/redoc").text
