"""The Google Sheets REST client: a service account signs a JWT, trades it for an access token,
then reads or writes one A1 range. Nothing here touches the database.

`make_client(info)` is the seam: it returns `FakeSheets` when SHEETS_FAKE=1 (local runs) and tests
replace it with their own stub. The value guard (`forbidden_formula`, `check_values`) and the A1
helpers are lifted from Cake OS `sheets_tools.py`; the token exchange follows MarCom's refresh.php.
"""

from __future__ import annotations

import json
import os
import re
import time
from urllib.parse import quote

import httpx
import jwt as pyjwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from backend.core.errors import Invalid

SCOPE = "https://www.googleapis.com/auth/spreadsheets"
API = "https://sheets.googleapis.com/v4/spreadsheets"
TOKEN_URI = "https://oauth2.googleapis.com/token"
TIMEOUT = 30
MAX_ROWS = 10_000  # data rows cached per sheet
MAX_WRITE_CELLS = 50_000


class SheetsError(Exception):
    """Google refused or could not be reached; the message is safe to show an admin."""


def parse_service_account(raw: str) -> dict:
    """The service-account key file's JSON, validated; Invalid when it is not one."""
    try:
        info = json.loads(raw)
    except (TypeError, ValueError):
        raise Invalid("service_account_json is not JSON") from None
    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise Invalid('service_account_json must be a key file with "type": "service_account"')
    if not info.get("client_email") or not info.get("private_key"):
        raise Invalid("service_account_json is missing client_email or private_key")
    try:
        load_pem_private_key(info["private_key"].encode(), password=None)
    except (TypeError, ValueError):
        raise Invalid("service_account_json has a private_key that does not load") from None
    return info


class GoogleSheets:
    def __init__(self, info: dict, transport: httpx.BaseTransport | None = None):
        self.info = info
        self.http = httpx.Client(timeout=TIMEOUT, transport=transport)
        self._token: str | None = None
        self._expires = 0.0

    def token(self) -> str:
        if self._token and self._expires > time.time() + 60:
            return self._token
        now = int(time.time())  # real time: Google checks iat/exp against its own clock
        token_uri = self.info.get("token_uri") or TOKEN_URI
        claims = {"iss": self.info["client_email"], "scope": SCOPE, "aud": token_uri, "iat": now, "exp": now + 3600}
        headers = {"kid": self.info["private_key_id"]} if self.info.get("private_key_id") else None
        assertion = pyjwt.encode(claims, self.info["private_key"], algorithm="RS256", headers=headers)
        body = self._call("POST", token_uri, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
        self._token, self._expires = body["access_token"], now + int(body.get("expires_in", 3600))
        return self._token

    def _call(self, method: str, url: str, **kwargs) -> dict:
        try:
            r = self.http.request(method, url, **kwargs)
        except httpx.HTTPError as e:
            raise SheetsError(f"Could not reach Google: {e.__class__.__name__}") from None
        if r.status_code >= 400:
            try:
                err = r.json().get("error")
                message = err.get("message") if isinstance(err, dict) else r.json().get("error_description") or err
            except (ValueError, AttributeError):
                message = None
            hint = ""
            if r.status_code in (403, 404):
                hint = f" Share the spreadsheet with {self.info['client_email']} (Viewer to read, Editor to write)."
            raise SheetsError(f"Google returned {r.status_code}: {message or r.reason_phrase}.{hint}")
        return r.json()

    def _values_url(self, spreadsheet_id: str, a1: str) -> str:
        return f"{API}/{quote(spreadsheet_id, safe='')}/values/{quote(a1, safe='')}"

    def read(self, spreadsheet_id: str, a1: str) -> list[list]:
        url = self._values_url(spreadsheet_id, bound_range(a1, MAX_ROWS))
        auth = {"Authorization": f"Bearer {self.token()}"}
        return self._call("GET", url, headers=auth, params={"majorDimension": "ROWS"}).get("values") or []

    def write(self, spreadsheet_id: str, a1: str, rows: list[list]) -> int:
        """Replace the range: clear it, then write `rows` from its top-left cell. Rows updated."""
        auth = {"Authorization": f"Bearer {self.token()}"}
        url = self._values_url(spreadsheet_id, a1)
        self._call("POST", f"{url}:clear", headers=auth, json={})
        body = self._call(
            "PUT", url, headers=auth, params={"valueInputOption": "USER_ENTERED"},
            json={"range": a1, "majorDimension": "ROWS", "values": rows},
        )
        return int(body.get("updatedRows", len(rows)))


class FakeSheets:
    """SHEETS_FAKE=1: a canned table and a write that only counts. Records calls for tests."""

    header = ["name", "color", "size"]
    data = [["Sprocket", "teal", "3"], ["Gear", "plum", "5"], ["Cog", "", "1"]]

    def __init__(self, info: dict | None = None):
        self.calls: list[tuple] = []

    def read(self, spreadsheet_id: str, a1: str) -> list[list]:
        self.calls.append(("read", spreadsheet_id, a1))
        return [list(self.header), *[list(r) for r in self.data]]

    def write(self, spreadsheet_id: str, a1: str, rows: list[list]) -> int:
        self.calls.append(("write", spreadsheet_id, a1, rows))
        return len(rows)


def make_client(info: dict) -> GoogleSheets | FakeSheets:
    return FakeSheets(info) if os.environ.get("SHEETS_FAKE") == "1" else GoogleSheets(info)


# ── Lifted from Cake OS backend/core/agents/tools/sheets_tools.py ─────────────────────
#
# A blanket refusal of external-fetch formulas: a cell is screened only when it is a formula
# (stripped text starts with "="). Formulas over the sheet's own cells (=SUM) are written live.
_IMPORT_FUNCS = ("IMPORTXML", "IMPORTDATA", "IMPORTHTML", "IMPORTFEED", "IMPORTRANGE", "IMAGE")
_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(_IMPORT_FUNCS) + r")\s*\(", re.IGNORECASE)


def forbidden_formula(value) -> str:
    """The external-fetch function this value calls, or ""."""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text.startswith("="):
        return ""
    match = _FORBIDDEN_RE.search(text)
    return match.group(1).upper() if match else ""


def check_values(values) -> str:
    """Why these rows may not be written, or "". Runs before any API call."""
    if not isinstance(values, list) or not values:
        return "rows must be a non-empty list of rows, each row a list of cell values"
    cells = 0
    for r, row in enumerate(values):
        if not isinstance(row, list):
            return f"Row {r + 1} is not a list; every row must be a list of cell values"
        cells += len(row)
        if cells > MAX_WRITE_CELLS:
            return f"That write is over {MAX_WRITE_CELLS:,} cells; write it in smaller blocks"
        for c, cell in enumerate(row):
            if isinstance(cell, (dict, list)):
                return f"Row {r + 1} column {c + 1} is not a single value"
            if func := forbidden_formula(cell):
                return (
                    f"Row {r + 1} column {c + 1} is a formula calling {func}, which makes the spreadsheet "
                    "fetch an external URL; write the value itself instead"
                )
    return ""


_A1_SPLIT_RE = re.compile(r"^(?:(?P<tab>'(?:[^']|'')*'|[^'!]+)!)?(?P<ref>.*)$", re.DOTALL)
_REF_RE = re.compile(r"^(?P<c0>[A-Za-z]{1,3})?(?P<r0>[0-9]{1,7})?(?::(?P<c1>[A-Za-z]{1,3})?(?P<r1>[0-9]{1,7})?)?$")


def quote_tab(title: str) -> str:
    """A tab title as an A1 prefix: always quoted, inner quotes doubled."""
    return "'" + str(title).replace("'", "''") + "'"


def unquote_tab(title: str) -> str:
    text = str(title or "").strip()
    if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'")
    return text


def split_a1(a1: str) -> tuple[str, str]:
    """"'Tab Name'!A1:F200" -> ("Tab Name", "A1:F200"). Tab is "" when absent."""
    match = _A1_SPLIT_RE.match(str(a1 or ""))
    if not match:
        return "", str(a1 or "")
    return unquote_tab(match.group("tab") or ""), (match.group("ref") or "").strip()


def col_to_index(letters: str) -> int | None:
    if not letters or not letters.isalpha():
        return None
    total = 0
    for ch in letters.upper():
        total = total * 26 + (ord(ch) - 64)
    return total - 1


def bound_range(a1: str, max_rows: int = MAX_ROWS) -> str:
    """The same range clamped to at most `max_rows + 1` rows (a header plus `max_rows`), so a
    whole-tab range on a huge tab is never downloaded in full. Unparseable refs pass through."""
    tab, ref = split_a1(a1)
    prefix = f"{quote_tab(tab)}!" if tab else ""
    if not ref:
        return f"{prefix}1:{max_rows + 1}"
    ref = ref.replace("$", "")
    match = _REF_RE.match(ref)
    if not match:
        if not tab:  # a bare tab title with no "!"
            return f"{quote_tab(unquote_tab(ref))}!1:{max_rows + 1}"
        return str(a1)
    c0, r0, c1, r1 = (match.group(n) for n in ("c0", "r0", "c1", "r1"))
    if ":" not in ref:
        if r0:
            return str(a1)
        if c0:
            return f"{prefix}{c0}1:{c0}{max_rows + 1}"
        return str(a1)
    start = int(r0) if r0 else 1
    end = int(r1) if r1 else None
    if end is not None and end < start:
        start, end = end, start
    if c0 and c1 and (col_to_index(c1) or 0) < (col_to_index(c0) or 0):
        c0, c1 = c1, c0
    if end is None or end - start + 1 > max_rows + 1:
        end = start + max_rows
    return f"{prefix}{c0 or ''}{start}:{c1 or ''}{end}"
