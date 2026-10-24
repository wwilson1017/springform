from backend.core.reminders.service import fire_due
from backend.core.scheduler import Job

JOBS = [Job("core.reminders_fire_due", fire_due, every=60)]
