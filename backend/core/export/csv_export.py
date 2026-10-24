"""CSV for people to open in a spreadsheet: UTF-8 with a BOM (so Excel reads accents), every
cell through `_cell`, served as an attachment.

`_cell` is lifted from CakeCRM `backend/crm/export.py`: spreadsheets run a cell that starts with
one of `_FORMULA_LEADS` as a formula, so such a cell gets an apostrophe and shows as text.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Iterable
from typing import Any, TextIO

from fastapi.responses import StreamingResponse

BOM = "﻿"
_FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, default=str)
    if isinstance(value, str) and value.startswith(_FORMULA_LEADS):
        return "'" + value
    return value


def write_csv(f: TextIO, header: list, rows: Iterable[Iterable]) -> int:
    """Header and rows to an open text file (no BOM). Returns the data rows written."""
    w = csv.writer(f)
    w.writerow([_cell(h) for h in header])
    n = 0
    for row in rows:
        w.writerow([_cell(v) for v in row])
        n += 1
    return n


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "export.csv"


def stream_csv(header: list, rows: Iterable[Iterable], filename: str) -> StreamingResponse:
    def chunks():
        buf = io.StringIO()
        buf.write(BOM)
        w = csv.writer(buf)
        w.writerow([_cell(h) for h in header])
        for row in rows:
            w.writerow([_cell(v) for v in row])
            if buf.tell() > 64_000:
                yield buf.getvalue().encode()
                buf.seek(0)
                buf.truncate()
        yield buf.getvalue().encode()

    return StreamingResponse(
        chunks(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename(filename)}"'},
    )
