import threading

from backend.core import scheduler
from backend.core.backup import service


def backup_job(cancel_event: threading.Event) -> None:
    # simplification: VACUUM INTO is not interrupted on cancel; a huge database can outlive the job
    # timeout (the scheduler holds the guard until it ends). Upgrade path: conn.interrupt() on cancel.
    service.run("job")


JOBS = [scheduler.Job("core.backup", backup_job, at="03:00")]
