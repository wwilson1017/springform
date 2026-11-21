"""Which AI tool is calling an MCP link, for provenance (docs/agents/mcp.md §1). Lifted from
todo-gtd `backend/common.py` (`client_name`; docs/PROVENANCE.md). The name is self-reported, so
it labels a run and never grants anything."""

from __future__ import annotations

import re

MAX_CHARS = 60
# How some tools name themselves, as a person would say it.
_FRIENDLY = {
    "claude-code": "Claude Code",
    "claude-ai": "Claude",
    "claude-user": "Claude",
    "openai-mcp": "ChatGPT",
}
# HTTP libraries, not AI tools: a name like this says nothing about who is calling.
_GENERIC = (
    "python", "node", "undici", "axios", "go-http", "okhttp", "curl", "mozilla", "java", "httpx",
    "aiohttp", "bun", "deno", "got", "fetch",
)  # fmt: skip
_PRODUCT = re.compile(r"\s*([A-Za-z][A-Za-z0-9 ._-]*?)\s*(?:/|\(|$)")


def client_name(declared, user_agent: str | None) -> str | None:
    """The name the client declares (MCP `clientInfo`), else the product its User-Agent leads
    with, never an HTTP library's; one printable line of at most MAX_CHARS, or None."""
    name = declared if isinstance(declared, str) and declared.strip() else None
    if not name:
        # Capped: the lazy class backtracks quadratically on a long run of spaces.
        match = _PRODUCT.match((user_agent or "")[:200])
        name = match.group(1) if match else None
        if name and name.lower().startswith(_GENERIC):
            name = None
    if not name:
        return None
    name = _FRIENDLY.get(name.strip().lower(), name)
    text = " ".join("".join(ch if ch.isprintable() else " " for ch in name).split())
    return text[:MAX_CHARS].strip() or None
