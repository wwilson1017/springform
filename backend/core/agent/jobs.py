from backend.core import scheduler
from backend.core.agent import detached

JOBS = [scheduler.Job("core.agent_turn_events_prune", detached.prune_events, every=86400)]
