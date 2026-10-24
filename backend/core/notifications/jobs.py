from backend.core.notifications.service import flush
from backend.core.scheduler import Job

JOBS = [Job("core.notifications_flush", flush, every=30)]
