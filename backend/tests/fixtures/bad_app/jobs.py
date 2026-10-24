from backend.core.scheduler import Job

JOBS = [Job(name="tidy", fn=lambda cancel: None, every=60)]
