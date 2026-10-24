"""The admin business-data export: one CSV per allowed table in a ZIP, plus manifest.json.

Tables come from `policy.CORE_EXPORT` and every installed app's `seed.EXPORT`; tables that do not
exist yet are skipped, and so are listed columns a table lacks. Rows follow the same rules as the
screen: each row's record must pass `entities.authorize(read)` for the exporting admin.
"""

from __future__ import annotations

import io
import json
import logging
import tempfile
import zipfile

from backend.core import VERSION, clock, db, entities
from backend.core.errors import NotFound
from backend.core.export import csv_export, policy

logger = logging.getLogger(__name__)


def merged_policy() -> dict[str, dict]:
    from backend.core import registry

    merged = dict(policy.CORE_EXPORT)
    for app in registry.installed():
        merged.update(getattr(app.modules["seed"], "EXPORT", {}))
    policy.check(merged)
    return merged


def tables_in(conn: db.Conn) -> list[tuple[str, dict, list[str]]]:
    """(table, spec, columns to export) for every allowed table that exists, in policy order."""
    existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    out = []
    for table, spec in merged_policy().items():
        if table not in existing:
            continue
        live = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
        if missing := [c for c in spec["columns"] if c not in live]:
            logger.warning("export: %s has no columns %s; exporting the rest", table, missing)
        out.append((table, spec, [c for c in spec["columns"] if c in live]))
    return out


def _from(table: str, spec: dict) -> str:
    return f'FROM "{table}"' + (f" WHERE {spec['where']}" if spec.get("where") else "")


def preview_in(conn: db.Conn) -> dict:
    """Row counts before row authorization, hence "estimated"."""
    return {
        "tables": [
            {"name": t, "columns": cols, "estimated_rows": conn.execute(f"SELECT count(*) {_from(t, spec)}").fetchone()[0]}
            for t, spec, cols in tables_in(conn)
        ]
    }


def preview() -> dict:
    return preview_in(db.get_conn())


def rows_in(conn: db.Conn, user, table: str, spec: dict, columns: list[str], allowed: dict):
    """The table's exportable rows for `user`; `allowed` caches (type, id) -> readable."""
    for row in conn.execute(f"SELECT * {_from(table, spec)} ORDER BY rowid"):
        row = dict(row)
        if spec.get("entity") is not None:
            key = (spec["entity"].format(**row), row[spec.get("id_column", "id")])
            if key not in allowed:
                try:
                    entities.authorize(user, conn, key[0], key[1], "read")
                    allowed[key] = True
                except NotFound:
                    allowed[key] = False
            if not allowed[key]:
                continue
        yield [row[c] for c in columns]


def export_in(conn: db.Conn, user) -> tuple[tempfile.SpooledTemporaryFile, str]:
    """The ZIP (rewound) and its filename."""
    now = clock.now_iso()
    buf = tempfile.SpooledTemporaryFile(max_size=32 * 2**20)  # spills to disk past 32 MB
    manifest = {"version": VERSION, "created_at": now, "exported_by": user.id, "tables": []}
    allowed: dict = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for table, spec, columns in tables_in(conn):
            member = zipfile.ZipInfo(f"{table}.csv", date_time=clock.parse(now).timetuple()[:6])
            member.compress_type = zipfile.ZIP_DEFLATED
            with z.open(member, "w") as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as f:
                n = csv_export.write_csv(f, columns, rows_in(conn, user, table, spec, columns, allowed))
            manifest["tables"].append({"name": table, "file": f"{table}.csv", "columns": columns, "rows": n})
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    buf.seek(0)
    return buf, f"springform-export-{now.replace(':', '').replace('-', '')}.zip"


def export(user) -> tuple[tempfile.SpooledTemporaryFile, str]:
    return export_in(db.get_conn(), user)
