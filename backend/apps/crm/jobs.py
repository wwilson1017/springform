from backend.apps.crm import scoring, touch_count
from backend.core.scheduler import Job

JOBS = [
    Job(name="crm.touch_count", fn=touch_count.run, every=120),
    Job(name="crm.scores_refresh", fn=scoring.refresh, every=3600),  # recency and age decay without a write
]
