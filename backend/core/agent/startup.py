import logging

from backend.core.agent import agents, history

logger = logging.getLogger(__name__)


def on_startup() -> None:
    """Seed Whisk if missing; tool runs left `executing` by a dead process become `interrupted`
    (the conversation shows them, and the model is told they may or may not have happened)."""
    agents.ensure_default()
    if n := history.mark_interrupted():
        logger.warning("Marked %d tool run(s) interrupted", n)
