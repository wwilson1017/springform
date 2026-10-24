from backend.apps.crm import touch_count
from backend.core.scheduler import Job

JOBS = [Job(name="crm.touch_count", fn=touch_count.run, every=120)]
