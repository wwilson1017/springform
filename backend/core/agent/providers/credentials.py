"""Provider keys and model tiers, stored in `core_agent_providers` (one row per vendor).

Rewritten from CakeCRM `providers/credentials.py` (Postgres `ai_providers` + `ai_settings`):
the key is encrypted with the install key (`secrets.encrypt`) and only ever leaves this module
as plaintext inside a provider object, never in an API response. A provider is usable when its
row is enabled and its key decrypts to something non-empty. Two tiers: `default` (chat) and
`light` (compaction, summaries, background work).
"""

from __future__ import annotations

from backend.core import db, secrets
from backend.core.clock import now_iso

PROVIDERS = ("anthropic", "openai")  # preference order when an agent names none
DEFAULT_MODELS = {
    "anthropic": {"default": "claude-opus-5-5", "light": "claude-haiku-5-5"},
    "openai": {"default": "gpt-5.5", "light": "gpt-5.4-nano"},
}


def _rows() -> dict[str, dict]:
    return {r["provider"]: r for r in db.rows("SELECT * FROM core_agent_providers")}


def _public(provider: str, row: dict | None) -> dict:
    row = row or {}
    return {
        "provider": provider,
        "has_key": bool(row.get("api_key_enc")),
        "enabled": bool(row.get("enabled", 1)),
        "model_default": row.get("model_default") or DEFAULT_MODELS[provider]["default"],
        "model_light": row.get("model_light") or DEFAULT_MODELS[provider]["light"],
        "updated_at": row.get("updated_at"),
    }


def list_providers() -> list[dict]:
    """Every known provider, configured or not, without keys."""
    rows = _rows()
    return [_public(p, rows.get(p)) for p in PROVIDERS]


def get_public(provider: str) -> dict:
    return _public(provider, _rows().get(provider))


def usable(prefer: str | None = None) -> dict | None:
    """The provider to call: `prefer` when it is usable, else the first usable one in order.
    Returns {provider, api_key, model_default, model_light} or None (zero keys)."""
    rows = _rows()
    for name in ([prefer] if prefer in PROVIDERS else []) + list(PROVIDERS):
        row = rows.get(name)
        if not row or not row["enabled"]:
            continue
        key = secrets.decrypt(row["api_key_enc"])
        if key:
            public = _public(name, row)
            return {"provider": name, "api_key": key, "model_default": public["model_default"], "model_light": public["model_light"]}
    return None


def update_in(
    conn: db.Conn, provider: str, *, api_key: str | None = None, model_default: str | None = None,
    model_light: str | None = None, enabled: bool | None = None,
) -> None:
    """Upsert one provider row. `api_key=""` removes the key; None leaves a field as it is."""
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}")
    conn.execute(
        "INSERT INTO core_agent_providers (provider, updated_at) VALUES (?, ?) ON CONFLICT (provider) DO NOTHING",
        (provider, now_iso()),
    )
    fields = {"model_default": model_default, "model_light": model_light}
    fields = {k: v.strip() for k, v in fields.items() if v is not None}
    if api_key is not None:
        fields["api_key_enc"] = secrets.encrypt(api_key.strip())
    if enabled is not None:
        fields["enabled"] = int(enabled)
    sets = "".join(f"{k} = ?, " for k in fields)  # keys are the literals above
    conn.execute(f"UPDATE core_agent_providers SET {sets}updated_at = ? WHERE provider = ?", (*fields.values(), now_iso(), provider))


def update(provider: str, **fields) -> dict:
    with db.transaction() as conn:
        update_in(conn, provider, **fields)
    return get_public(provider)
