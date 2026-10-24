"""The published sheets client for apps.

    from backend.core.sheets import api as sheets
    data = sheets.client("example").read("widgets")   # SheetData, from the cache only

`read` and `status` never call Google; they serve what the last refresh cached, so they are safe
on any request path and have `_in(conn, ...)` forms. `write` calls Google and must run outside
`transaction()` (it raises inside one); it has no `_in` form.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.core import db
from backend.core.sheets import service


@dataclass(frozen=True)
class SheetData:
    header: list[str]
    rows: list[list[str]]  # every row padded to the header's width; all cells are strings
    fetched_at: str | None  # None when nothing has been fetched yet
    stale: bool  # nothing cached, the last refresh failed, or the cache is older than twice its schedule


class SheetsClient:
    def __init__(self, slug: str):
        self.slug = slug

    def read_in(self, conn: db.Conn, name: str) -> SheetData:
        sheet = service.find_in(conn, self.slug, name)
        cache = service.cached_in(conn, sheet["id"])
        if cache is None:
            return SheetData([], [], None, True)
        return SheetData(cache["header"], cache["rows"], cache["fetched_at"], service.is_stale(sheet))

    def read(self, name: str) -> SheetData:
        return self.read_in(db.get_conn(), name)

    def status_in(self, conn: db.Conn, name: str) -> dict:
        s = service.find_in(conn, self.slug, name)
        return {k: s[k] for k in ("configured", "enabled", "last_synced_at", "last_error", "row_count")}

    def status(self, name: str) -> dict:
        return self.status_in(db.get_conn(), name)

    def write(self, name: str, rows: list[list]) -> int:
        """Replace the sheet's range with `rows` (write-mode sheets only). Rows written."""
        return service.write(self.slug, name, rows)


def client(slug: str) -> SheetsClient:
    """Raises NotFound from read/status/write when the app declares no such sheet."""
    return SheetsClient(slug)
