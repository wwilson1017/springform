from backend.core.requests import service
from backend.core.scheduler import Job


def refresh_board(cancel) -> None:
    """Job core.requests_refresh: a no-op until GitHub is configured."""
    if service.config()["configured"]:
        service.refresh(cancel)


JOBS = [Job("core.requests_refresh", refresh_board, every=900, timeout=120)]
