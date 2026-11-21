from backend.core import scheduler
from backend.core.checkins import service

JOBS = [scheduler.Job(service.JOB, service.run_due, every=60, timeout=1800)]
