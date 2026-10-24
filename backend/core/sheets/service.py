"""Connected sheets: the service-account key, the sheet rows apps declare, refresh and the cache.

Network rule: `refresh` and `write` call Google outside any transaction and record the result in
a transaction of their own afterwards, so they have no `_in` form and refuse to run inside one.
Every other function has `fn(...)` and `fn_in(conn, ...)` forms.

Schedules (the hourly job `core.sheets_refresh` reads them): `hourly` refreshes on every job run,
`daily` when the last successful sync is older than 23 h (so once a day on an hourly job),
`manual` only from the admin's refresh button. The job refreshes enabled read sheets only.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from backend.core import clock, db, settings
from backend.core.errors import AppError, Conflict, Invalid, NotFound
from backend.core.sheets import google

KEY = "sheets.service_account_json"
SCHEDULES = ("hourly", "daily", "manual")
THROTTLE_SECONDS = 60
DAILY_AFTER = 23 * 3600
STALE_AFTER = {"hourly": 2 * 3600, "daily": 2 * 86400}  # manual sheets are stale only when never fetched
PREVIEW_ROWS = 20
_SHEET_URL = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")
_SHEET_ID = re.compile(r"^[A-Za-z0-9_-]*$")


class SheetsUnavailable(AppError):
    status, default = 502, "sheets_unavailable"


class Throttled(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"throttled; retry after {retry_after}s")


# ── Credentials ──────────────────────────────────────────────────────────────────────


def service_account() -> dict | None:
    return settings.get_setting(KEY) or None


def credentials_status() -> dict:
    """Never the key itself: whether one is set, and the address to share sheets with."""
    info = service_account()
    return {"configured": info is not None, "service_account_email": info["client_email"] if info else None}


def set_credentials_in(conn: db.Conn, raw: str, user_id: int) -> None:
    settings.set_setting_in(conn, KEY, google.parse_service_account(raw), user_id, is_secret=True)


def set_credentials(raw: str, user_id: int) -> dict:
    with db.transaction() as conn:
        set_credentials_in(conn, raw, user_id)
    return credentials_status()


# ── Sheet rows ───────────────────────────────────────────────────────────────────────

_SELECT = """SELECT s.id, s.app, s.name, s.description, s.spreadsheet_id, s.range, s.mode, s.schedule, s.enabled,
                    s.last_synced_at, s.last_error, s.row_count, s.created_at, s.updated_at, c.fetched_at
               FROM core_connected_sheets s LEFT JOIN core_sheet_cache c ON c.sheet_id = s.id"""


def _sheet(row) -> dict:
    sheet = dict(row)
    sheet["enabled"] = bool(sheet["enabled"])
    sheet["configured"] = bool(sheet["spreadsheet_id"] and sheet["range"])
    return sheet


def list_sheets_in(conn: db.Conn) -> list[dict]:
    return [_sheet(r) for r in conn.execute(f"{_SELECT} ORDER BY s.app, s.name")]


def list_sheets() -> list[dict]:
    return list_sheets_in(db.get_conn())


def get_sheet_in(conn: db.Conn, sheet_id: int) -> dict:
    row = conn.execute(f"{_SELECT} WHERE s.id = ?", (sheet_id,)).fetchone()
    if row is None:
        raise NotFound("no such sheet")
    return _sheet(row)


def find_in(conn: db.Conn, app: str, name: str) -> dict:
    row = conn.execute(f"{_SELECT} WHERE s.app = ? AND s.name = ?", (app, name)).fetchone()
    if row is None:
        raise NotFound(f"app {app!r} declares no sheet {name!r}")
    return _sheet(row)


def seed_in(conn: db.Conn, declared: list[tuple[str, Any]]) -> None:
    """One row per (app slug, manifest Sheet); idempotent. A changed description or mode is
    updated; admin settings are kept. Rows for sheets no longer declared are left in place."""
    now = clock.now_iso()
    for app, sheet in declared:
        conn.execute(
            """INSERT INTO core_connected_sheets (app, name, description, mode, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (app, name) DO UPDATE SET description = excluded.description, mode = excluded.mode,
                      updated_at = excluded.updated_at
               WHERE description != excluded.description OR mode != excluded.mode""",
            (app, sheet.name, sheet.description, sheet.mode, now, now),
        )


def seed() -> None:
    from backend.core import registry

    with db.transaction() as conn:
        seed_in(conn, [(app.slug, s) for app in registry.installed() for s in app.manifest.sheets])


def update_sheet_in(conn: db.Conn, sheet_id: int, patch: dict) -> dict:
    """patch: any of spreadsheet_id (an id or the sheet's URL), range, enabled, schedule.
    Pointing a sheet somewhere else drops its cache and status."""
    before = get_sheet_in(conn, sheet_id)
    fields: dict[str, Any] = {}
    if "spreadsheet_id" in patch:
        value = str(patch["spreadsheet_id"]).strip()
        value = m.group(1) if (m := _SHEET_URL.search(value)) else value
        if not _SHEET_ID.match(value):
            raise Invalid("spreadsheet_id: paste the spreadsheet's id or its URL")
        fields["spreadsheet_id"] = value
    if "range" in patch:
        fields["range"] = str(patch["range"]).strip()
    if "enabled" in patch:
        fields["enabled"] = int(bool(patch["enabled"]))
    if "schedule" in patch:
        if patch["schedule"] not in SCHEDULES:
            raise Invalid(f"schedule must be one of {', '.join(SCHEDULES)}")
        fields["schedule"] = patch["schedule"]
    if not fields:
        return before
    sets = ", ".join(f"{k} = ?" for k in fields)  # keys are the fixed names above
    conn.execute(f"UPDATE core_connected_sheets SET {sets}, updated_at = ? WHERE id = ?", (*fields.values(), clock.now_iso(), sheet_id))
    if any(k in fields and fields[k] != before[k] for k in ("spreadsheet_id", "range")):
        conn.execute("DELETE FROM core_sheet_cache WHERE sheet_id = ?", (sheet_id,))
        conn.execute(
            "UPDATE core_connected_sheets SET last_synced_at = NULL, last_error = NULL, row_count = NULL WHERE id = ?",
            (sheet_id,),
        )
    return get_sheet_in(conn, sheet_id)


def update_sheet(sheet_id: int, patch: dict) -> dict:
    with db.transaction() as conn:
        return update_sheet_in(conn, sheet_id, patch)


# ── Cache ────────────────────────────────────────────────────────────────────────────


def cached_in(conn: db.Conn, sheet_id: int) -> dict | None:
    row = conn.execute("SELECT fetched_at, header, rows FROM core_sheet_cache WHERE sheet_id = ?", (sheet_id,)).fetchone()
    if row is None:
        return None
    return {"fetched_at": row["fetched_at"], "header": json.loads(row["header"]), "rows": json.loads(row["rows"])}


def is_stale(sheet: dict) -> bool:
    """No cache yet, the last refresh failed, or the cache is older than twice its schedule."""
    if not sheet["fetched_at"] or sheet["last_error"]:
        return True
    limit = STALE_AFTER.get(sheet["schedule"])
    return limit is not None and sheet["fetched_at"] < clock.ago(limit)


def preview_in(conn: db.Conn, sheet_id: int, limit: int = PREVIEW_ROWS) -> dict:
    sheet = get_sheet_in(conn, sheet_id)
    cache = cached_in(conn, sheet_id) or {"fetched_at": None, "header": [], "rows": []}
    return {
        "header": cache["header"], "rows": cache["rows"][:limit], "fetched_at": cache["fetched_at"],
        "row_count": sheet["row_count"], "stale": is_stale(sheet),
    }


def preview(sheet_id: int, limit: int = PREVIEW_ROWS) -> dict:
    return preview_in(db.get_conn(), sheet_id, limit)


def store_cache_in(conn: db.Conn, sheet_id: int, values: list[list]) -> int:
    """The first row is the header; every row becomes strings, padded to the header's width."""
    header = [str(v) for v in values[0]] if values else []
    rows = [[str(v) for v in r] + [""] * (len(header) - len(r)) for r in values[1:]]
    now = clock.now_iso()
    conn.execute(
        """INSERT INTO core_sheet_cache (sheet_id, fetched_at, header, rows) VALUES (?, ?, ?, ?)
           ON CONFLICT (sheet_id) DO UPDATE SET fetched_at = excluded.fetched_at, header = excluded.header,
                                                rows = excluded.rows""",
        (sheet_id, now, json.dumps(header), json.dumps(rows)),
    )
    conn.execute(
        "UPDATE core_connected_sheets SET last_synced_at = ?, last_error = NULL, row_count = ? WHERE id = ?",
        (now, len(rows), sheet_id),
    )
    return len(rows)


def record_error_in(conn: db.Conn, sheet_id: int, message: str) -> None:
    conn.execute("UPDATE core_connected_sheets SET last_error = ? WHERE id = ?", (message[:1000], sheet_id))


def _claim_attempt(sheet_id: int, manual: bool) -> None:
    """Stamp the attempt; a manual refresh within THROTTLE_SECONDS of the last one is refused."""
    now = clock.now_iso()
    with db.transaction() as conn:
        if manual:
            last = conn.execute("SELECT last_attempt_at FROM core_connected_sheets WHERE id = ?", (sheet_id,)).fetchone()[0]
            if last and last > clock.ago(THROTTLE_SECONDS):
                wait = THROTTLE_SECONDS - (clock.now() - clock.parse(last)).total_seconds()
                raise Throttled(max(1, math.ceil(wait)))
        conn.execute("UPDATE core_connected_sheets SET last_attempt_at = ? WHERE id = ?", (now, sheet_id))


def _failed(e: Exception) -> str:
    return str(e) if isinstance(e, google.SheetsError) else f"{e.__class__.__name__}: {e}"


def refresh(sheet_id: int, *, manual: bool = False, sheets: Any = None) -> dict:
    """Fetch the sheet's range from Google now and replace its cache. Returns the sheet row.

    404 missing; 422 no spreadsheet_id/range; 409 no service-account key; Throttled (the route's
    429) for a manual refresh inside the throttle; 502 when Google fails (also kept in last_error).
    `sheets` lets the hourly job reuse one client (one access token) across sheets."""
    if db.in_transaction():
        raise RuntimeError("sheets.refresh calls Google; run it outside transaction()")
    sheet = get_sheet_in(db.get_conn(), sheet_id)
    if not sheet["configured"]:
        raise Invalid("Set the sheet's spreadsheet_id and range first")
    info = service_account()
    if info is None:
        raise Conflict("Add the Google service-account key first")
    _claim_attempt(sheet_id, manual)
    try:
        values = (sheets or google.make_client(info)).read(sheet["spreadsheet_id"], sheet["range"])
    except Exception as e:
        with db.transaction() as conn:
            record_error_in(conn, sheet_id, _failed(e))
        raise SheetsUnavailable(_failed(e)) from e
    with db.transaction() as conn:
        store_cache_in(conn, sheet_id, values)
        return get_sheet_in(conn, sheet_id)


def due_in(conn: db.Conn) -> list[dict]:
    """Sheets the hourly job should refresh now."""
    rows = conn.execute(
        f"""{_SELECT} WHERE s.enabled = 1 AND s.mode = 'read' AND s.spreadsheet_id != '' AND s.range != ''
              AND (s.schedule = 'hourly'
                   OR (s.schedule = 'daily' AND (s.last_synced_at IS NULL OR s.last_synced_at <= ?)))
            ORDER BY s.id""",
        (clock.ago(DAILY_AFTER),),
    )
    return [_sheet(r) for r in rows]


# ── Writes (the published client's write) ───────────────────────────────────────────


def write(app: str, name: str, rows: list[list], *, sheets: Any = None) -> int:
    """Replace a write-mode sheet's range with `rows`. Returns the rows Google updated.

    Refuses (422) a read-mode sheet, rows that fail `check_values` (shape, size, a formula that
    fetches an external URL); 409 when the sheet is disabled, unconfigured or there is no key;
    502 when Google fails (kept in last_error). The cache is not touched."""
    if db.in_transaction():
        raise RuntimeError("sheets write calls Google; run it outside transaction()")
    sheet = find_in(db.get_conn(), app, name)
    if sheet["mode"] != "write":
        raise Invalid(f"sheet {app}.{name} is read-only")
    if problem := google.check_values(rows):
        raise Invalid(problem)
    if not sheet["enabled"] or not sheet["configured"]:
        raise Conflict(f"sheet {app}.{name} is disabled or has no spreadsheet_id/range")
    info = service_account()
    if info is None:
        raise Conflict("Add the Google service-account key first")
    values = [["" if v is None else v for v in row] for row in rows]
    try:
        n = (sheets or google.make_client(info)).write(sheet["spreadsheet_id"], sheet["range"], values)
    except Exception as e:
        with db.transaction() as conn:
            record_error_in(conn, sheet["id"], _failed(e))
        raise SheetsUnavailable(_failed(e)) from e
    with db.transaction() as conn:
        conn.execute(
            "UPDATE core_connected_sheets SET last_synced_at = ?, last_error = NULL, row_count = ? WHERE id = ?",
            (clock.now_iso(), n, sheet["id"]),
        )
    return n
