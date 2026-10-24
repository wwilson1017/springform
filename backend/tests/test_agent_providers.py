"""Zero keys, provider admin routes, llm.complete and the agents routes."""

import pytest

from backend.core import db as core_db
from backend.core.agent import llm
from backend.core.agent.providers import NoProviderConfigured, ProviderError, fake, get_provider

KEY = "sk-ant-test-0123456789-secret"


@pytest.fixture(autouse=True)
def _no_fake(monkeypatch):
    monkeypatch.delenv("AGENT_FAKE_PROVIDER", raising=False)
    fake.reset()


def test_zero_keys_status_and_chat_400_while_the_rest_works(login_as):
    a = login_as("member")
    s = a.get("/api/agent/status").json()
    assert s["configured"] is False and s["default_agent"] == "whisk" and s["models"] == {"default": None, "light": None}
    assert {p["provider"]: p["has_key"] for p in s["providers"]} == {"anthropic": False, "openai": False}
    r = a.post("/api/agent/chat", json={"message": "hi"})
    assert (r.status_code, r.json()) == (400, {"detail": "no_provider"})
    assert a.get("/api/agent/agents").json()[0]["slug"] == "whisk"
    assert a.post("/api/agent/conversations", json={}).status_code == 200
    assert get_provider() is None


def test_provider_routes_are_admin_only_and_never_leak_keys(login_as):
    admin, member = login_as("admin"), login_as("member")
    assert member.get("/api/agent/providers").status_code == 403
    assert member.put("/api/agent/providers/anthropic", json={"api_key": KEY}).status_code == 403
    assert admin.put("/api/agent/providers/nope", json={"api_key": KEY}).status_code == 404

    r = admin.put("/api/agent/providers/anthropic", json={"api_key": KEY, "model_light": "claude-haiku-5-5"})
    assert r.status_code == 200 and KEY not in r.text and r.json()["has_key"] is True
    stored = core_db.one("SELECT api_key_enc FROM core_agent_providers WHERE provider = 'anthropic'")["api_key_enc"]
    assert stored.startswith("enc:v1:") and KEY not in stored
    for path in ("/api/agent/providers", "/api/agent/status"):
        assert KEY not in admin.get(path).text
    status = admin.get("/api/agent/status").json()
    assert status["configured"] is True and status["models"] == {"default": "claude-opus-5-5", "light": "claude-haiku-5-5"}
    provider = get_provider(tier="light")
    assert (provider.provider_name, provider.model) == ("anthropic", "claude-haiku-5-5")

    assert admin.put("/api/agent/providers/anthropic", json={"enabled": False}).json()["enabled"] is False
    assert admin.get("/api/agent/status").json()["configured"] is False
    admin.put("/api/agent/providers/anthropic", json={"enabled": True, "api_key": ""})
    assert admin.get("/api/agent/status").json()["configured"] is False


def test_provider_test_route_without_a_key_is_400(login_as):
    admin = login_as("admin")
    r = admin.post("/api/agent/providers/openai/test")
    assert (r.status_code, r.json()["detail"]) == (400, "no_key")


def test_llm_complete(db, monkeypatch):
    with pytest.raises(NoProviderConfigured):
        llm.complete("system", "hello")
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    assert llm.complete("system", "hello") == "You said: hello"
    fake.script({"error": "bad key"})
    with pytest.raises(ProviderError, match="bad key"):
        llm.complete("system", "hello")
    with core_db.transaction(), pytest.raises(RuntimeError, match="inside transaction"):
        llm.complete("system", "hello")


def test_agents_routes(login_as):
    admin, member = login_as("admin"), login_as("member")
    whisk = member.get("/api/agent/agents").json()[0]
    assert (whisk["name"], whisk["is_default"], whisk["model_tier"]) == ("Whisk", True, "default") and whisk["soul"]
    assert member.patch("/api/agent/agents/whisk", json={"name": "Pip"}).status_code == 403
    r = admin.patch("/api/agent/agents/whisk", json={"personality": "Answer in haiku.", "model_tier": "light"})
    assert r.status_code == 200 and (r.json()["personality"], r.json()["model_tier"]) == ("Answer in haiku.", "light")
    assert admin.patch("/api/agent/agents/nobody", json={"name": "x"}).status_code == 404
    assert admin.patch("/api/agent/agents/whisk", json={"model_tier": "huge"}).status_code == 422
