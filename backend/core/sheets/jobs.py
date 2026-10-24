import logging
import threading

from backend.core import db, scheduler
from backend.core.sheets import google, service

logger = logging.getLogger(__name__)


def refresh_due(cancel: threading.Event) -> None:
    """Job core.sheets_refresh: refresh every due read sheet (see service's schedules). Each
    sheet's failure lands in its last_error; the job itself never raises."""
    try:
        info = service.service_account()
        if info is None:
            return
        sheets = google.make_client(info)  # one access token for the whole run
        for sheet in service.due_in(db.get_conn()):
            if cancel.is_set():
                return
            try:
                service.refresh(sheet["id"], sheets=sheets)
            except Exception as e:
                logger.warning("sheet %s.%s did not refresh: %s", sheet["app"], sheet["name"], e)
    except Exception:
        logger.exception("core.sheets_refresh failed")


JOBS = [scheduler.Job("core.sheets_refresh", refresh_due, every=3600)]
