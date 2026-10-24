"""Model providers, chosen from `core_agent_providers` at call time (CakeCRM `providers/__init__.py`).

Zero keys is a normal state: `get_provider()` returns None and `status()["configured"]` is
false; the rest of the install never notices. Vendor SDKs are imported only inside the vendor
modules. AGENT_FAKE_PROVIDER=1 swaps in the scripted FakeProvider for tests and local demos.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from backend.core.agent.providers import credentials
from backend.core.agent.providers.base import AIProvider

TIERS = ("default", "light")


class NoProviderConfigured(RuntimeError):
    """No usable AI key on this install."""


class ProviderError(RuntimeError):
    """The provider answered with an error (bad key, rate limit, outage)."""


def fake_enabled() -> bool:
    return os.environ.get("AGENT_FAKE_PROVIDER") == "1"


def make(provider: str, api_key: str, model: str) -> AIProvider:
    if provider == "anthropic":
        from backend.core.agent.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key, model)
    if provider == "openai":
        from backend.core.agent.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(api_key, model)
    raise ValueError(f"unknown provider {provider!r}")


def get_provider(*, tier: str = "default", provider: str | None = None, model: str | None = None) -> AIProvider | None:
    """The provider for a call, or None with zero keys. `provider` is an agent's override (used
    when usable, else the install's first usable provider); `model` overrides the tier's model
    only when that provider is the one chosen."""
    if fake_enabled():
        from backend.core.agent.providers.fake import FakeProvider

        return FakeProvider(model or f"fake-{tier}")
    row = credentials.usable(provider)
    if row is None:
        return None
    chosen_model = model if (model and row["provider"] == provider) else row[f"model_{tier}"]
    return make(row["provider"], row["api_key"], chosen_model)


def status() -> dict:
    """{configured, providers: [{provider, has_key, enabled, model_default, model_light, updated_at}],
    default_model, light_model}. Never carries a key."""
    if fake_enabled():
        return {"configured": True, "providers": credentials.list_providers(), "default_model": "fake-default", "light_model": "fake-light"}
    row = credentials.usable()
    return {
        "configured": row is not None,
        "providers": credentials.list_providers(),
        "default_model": row["model_default"] if row else None,
        "light_model": row["model_light"] if row else None,
    }


async def collect_text(stream: AsyncIterator[dict]) -> str:
    """Drive one provider stream to its text; ProviderError on an error event or a dead stream."""
    text, completed = "", False
    async for event in stream:
        if event["type"] == "text":
            text += event["text"]
        elif event["type"] == "error":
            raise ProviderError(event["error"])
        elif event["type"] == "_turn_complete":
            completed = True
            break
    if not completed:
        raise ProviderError("The model response ended unexpectedly.")
    return text
