"""The skills jobs: `core.skills_review` (every 5 minutes; it reviews once ten more turns have
finished, while `agent.skills_review_enabled` is on) and `core.skills_curate` (daily)."""

from __future__ import annotations

import logging
import threading

from backend.core import scheduler, settings, skills
from backend.core.skills import review

logger = logging.getLogger(__name__)

ENABLED_SETTING = "agent.skills_review_enabled"


def run_review(cancel: threading.Event | None = None) -> dict:
    if not settings.get_setting(ENABLED_SETTING, False):
        return {"status": "skipped", "reason": "disabled"}
    from backend.core.agent.llm import NoProviderConfigured, complete

    def call(system: str, prompt: str) -> str:
        try:
            return complete(system, prompt, tier=review.TIER, max_tokens=review.MAX_TOKENS, source="skills")
        except NoProviderConfigured:
            raise review.ProviderMissing from None

    result = review.run(call, cancel)
    logger.info("core.skills_review: %s", result)
    return result


def run_curate(cancel: threading.Event | None = None) -> dict:
    archived = skills.curate()
    if archived:
        logger.info("core.skills_curate: archived %d unused skills", archived)
    return {"status": "ok", "archived": archived}


JOBS = [
    scheduler.Job("core.skills_review", run_review, every=300, timeout=600),
    # `at`, not `every`: a never-run `every` job is due at the first tick of every start
    scheduler.Job("core.skills_curate", run_curate, at="03:15"),
]
