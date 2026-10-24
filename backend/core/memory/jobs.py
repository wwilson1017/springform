"""`core.agent_nightly` at 02:00: the observer, then dreaming.

Skipped (logged, nothing written) when the `agent.nightly_enabled` setting is off (the
default), when the engine's `llm` module is absent, or when it has no configured provider.
"""

from __future__ import annotations

import logging
import threading

from backend.core import scheduler, settings
from backend.core.memory import dreaming, observer

logger = logging.getLogger(__name__)

ENABLED_SETTING = "agent.nightly_enabled"
MAX_TOKENS = 2048  # up to 8 facts of 300 chars, plus headroom: thinking counts against max_tokens


def nightly(cancel: threading.Event | None = None) -> dict:
    if not settings.get_setting(ENABLED_SETTING, False):
        return _skipped("disabled")
    try:
        from backend.core.agent.llm import NoProviderConfigured, complete
    except ImportError:
        return _skipped("no_llm_module")

    def light(system: str, prompt: str) -> str:
        try:
            return complete(system, prompt, tier="light", max_tokens=MAX_TOKENS)
        except NoProviderConfigured:
            raise observer.ProviderMissing from None

    seen = observer.observe(light, cancel)
    if seen["status"] == "skipped":
        return _skipped(seen["reason"])
    result = {"status": "ok", "observer": seen, "dreaming": dreaming.consolidate()}
    logger.info("core.agent_nightly: %s", result)
    return result


def _skipped(reason: str) -> dict:
    logger.info("core.agent_nightly skipped: %s", reason)
    return {"status": "skipped", "reason": reason}


JOBS = [scheduler.Job("core.agent_nightly", nightly, at="02:00", timeout=1800)]
