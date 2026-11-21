import logging

from backend.core.agent import agents, detached, execute, history

logger = logging.getLogger(__name__)


def on_startup() -> None:
    """Seed Whisk if missing; tool runs left `executing` and turns left `running` by a dead process
    become `interrupted` (the conversation shows the runs, and the model is told they may or may not
    have happened; a turn's log ends with an `interrupted` error event)."""
    agents.ensure_default()
    if n := history.mark_interrupted():
        logger.warning("Marked %d tool run(s) interrupted", n)
    if n := detached.mark_interrupted():
        logger.warning("Marked %d agent turn(s) interrupted", n)
    if n := execute.backfill_records():
        logger.info("Recorded what %d older tool result(s) name, for the replay recheck", n)
