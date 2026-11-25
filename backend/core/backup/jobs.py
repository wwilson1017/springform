import threading

from backend.core import scheduler
from backend.core.backup import service


def backup_job(cancel_event: threading.Event) -> None:
    # simplification: VACUUM INTO is not interrupted on cancel; a huge database can outlive the job
    # timeout (the scheduler holds the guard until it ends). Upgrade path: conn.interrupt() on cancel.
    # The off-site copy checks the event between objects; the next run skips what is already there.
    service.run("job", cancel_event)


# An hour: the off-site copy's first upload of a big install's attachments can take a while.
JOBS = [scheduler.Job("core.backup", backup_job, at="03:00", timeout=3600)]
