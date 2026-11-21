"""Photos and files attached to a chat message (agent.md §5, "Uploads"; lifted from CakeCRM
`assistant/uploads.py`).

`accept_into` stages each file with `files.storage.stage` (the `files.max_bytes` cap; photos also
3.75 MB, since Anthropic caps a base64 image at 5 MB) and reads it from the staged path: a photo's
header through Pillow (refused, never re-encoded), a CSV decoded, XLSX, DOCX and PDF text extracted
by parsers imported lazily, so an install without them still boots and only refuses those types.
Each file becomes a block on the untrusted fence. Photos, CSV and XLSX keep their bytes as a
`core_file_blobs` blob held by a `core_agent_uploads` row; PDF and DOCX keep only their text.

`save_in` runs inside `detached._begin`'s transaction: the blob, the row, the rename into place
and the message's `files` list. A staged file belongs to whoever holds the `Upload` until then;
`discard` drops it on every path that does not reach `save_in`.

`read` is the `core_read_upload` handler: rows of a kept CSV or XLSX, for its own user, from the
conversation it was attached in.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import re
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from backend.core import clock, db
from backend.core.agent import delimiters
from backend.core.agent.spec import calling_conversation
from backend.core.errors import AppError, Invalid, NotFound
from backend.core.files import service as files_service, storage

MAX_FILES = 5
MAX_IMAGE_BYTES = 5 * 1024 * 1024 * 3 // 4  # Anthropic caps the base64 image at 5 MB; base64 adds a third
MAX_IMAGE_EDGE = 8000
MAX_CHARS = 50_000  # extracted text kept per file
MAX_UNZIPPED_BYTES = 200 * 1024 * 1024  # DOCX and XLSX are zips: refuse a bomb before parsing
ENVELOPE_BYTES = 1024 * 1024  # multipart overhead allowed on top of MAX_FILES x the file cap
READ_ROWS = 200
READ_CHARS = 20_000  # one core_read_upload page, under result_cap.CAP_CHARS
TITLE = "Attached files"  # a files-only message's title: filenames never become titles

# simplification: the issue's types only; txt, md and json are one entry each away.
KINDS = {"jpg": "image", "jpeg": "image", "png": "image", "webp": "image", "csv": "table", "xlsx": "table"}
KINDS |= {"pdf": "document", "docx": "document"}
_IMAGE_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
_TABLE_MIME = {"csv": "text/csv", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
NOT_FOUND = "No readable upload with that id in this conversation."
_RANGE_RE = re.compile(r"([A-Z]*)(\d*)(?::([A-Z]*)(\d*))?")


class UploadError(AppError):
    """A user-facing refusal; the detail is a sentence the chat shows as is."""

    status, default = 400, "upload_refused"


@dataclass(frozen=True)
class Upload:
    filename: str
    kind: str  # image | table | document
    mime_type: str
    text: str  # the fenced block the model reads
    staged: storage.Staged | None  # kept bytes (image, table); None for a document


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.3g}"


# ── Accepting ─────────────────────────────────────────────────────────────────


def accept_into(out: list[Upload], files: Iterable[tuple[str | None, BinaryIO]], *, vision: bool, model: str, cap: int):
    """Check, stage and read each file, appending an `Upload` to `out` once it is accepted, so a
    caller that catches the first refusal can still `discard(out)`. Runs in a worker thread."""
    for raw_name, src in files:
        name = files_service.normalize_filename(raw_name)
        ext = _ext(name)
        if ext in ("heic", "heif"):
            raise UploadError("HEIC photos aren't supported. Save it as a JPEG or PNG first.")
        if ext == "gif":
            raise UploadError("GIFs aren't supported. Attach a JPEG, PNG or WebP photo.")
        kind = KINDS.get(ext)
        if kind is None:
            raise UploadError(f"'{name}' isn't a type the assistant reads. Allowed: {', '.join(sorted(KINDS))}.")
        if kind == "image" and not vision:
            raise UploadError(
                f"{model} can't see photos. Attach a document instead, or ask an admin for a model that can."
            )
        limit = min(cap, MAX_IMAGE_BYTES) if kind == "image" else cap
        src.seek(0)
        try:
            staged = storage.stage(src, limit)
        except storage.TooLarge:
            raise storage.TooLarge(f"'{name}' is larger than the {_mb(limit)} MB limit.") from None
        try:
            out.append(_read(name, ext, kind, staged))
        except BaseException:
            staged.path.unlink(missing_ok=True)
            raise


def _read(name: str, ext: str, kind: str, staged: storage.Staged) -> Upload:
    path = staged.path
    try:
        if kind == "image":
            mime = _image_mime(name, path)
            return Upload(
                name,
                kind,
                mime,
                delimiters.wrap_untrusted_upload(name, delimiters.IMAGE_PLACEHOLDER, image=True),
                staged,
            )
        if ext == "csv":
            text = _decode(path.read_bytes(), name)
        elif ext == "xlsx":
            text = _xlsx_text(path)
        elif ext == "pdf":
            text = _pdf_text(path, name)
        else:
            text = _docx_text(path)
    except ImportError:
        raise UploadError(f"This install can't read .{ext} files.") from None
    except AppError:
        raise
    except Exception:
        raise UploadError(f"Could not read '{name}'.") from None
    if len(text) > MAX_CHARS:
        cut = text.rfind("\n", 0, MAX_CHARS)
        text = text[: cut if cut > 0 else MAX_CHARS] + f"\n\n(truncated at {MAX_CHARS:,} characters)"
    elif not text.strip():
        text = "(No extractable text found.)"
    block = delimiters.wrap_untrusted_upload(name, text)
    if kind == "document":
        path.unlink(missing_ok=True)
        return Upload(name, kind, "", block, None)
    return Upload(name, kind, _TABLE_MIME[ext], block, staged)


def _image_mime(name: str, path: Path) -> str:
    from PIL import Image

    try:
        with Image.open(path, formats=list(_IMAGE_MIME)) as im:
            fmt, (w, h) = im.format, im.size
    except Exception:
        raise UploadError(f"'{name}' is not a JPEG, PNG or WebP image.") from None
    if max(w, h) > MAX_IMAGE_EDGE:
        raise UploadError(f"'{name}' is larger than {MAX_IMAGE_EDGE} px on a side. Shrink it first.")
    return _IMAGE_MIME[str(fmt)]


def _decode(data: bytes, name: str) -> str:
    if b"\x00" in data:
        raise UploadError(f"'{name}' isn't a text CSV.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _zip_guard(path: Path) -> None:
    with zipfile.ZipFile(path) as z:
        if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED_BYTES:
            raise UploadError("That file unpacks to more than the assistant will read.")


def _bounded(lines: Iterable[str]) -> str:
    """Join lines until a little past MAX_CHARS (the caller cuts and adds the footer)."""
    out, total = [], 0
    for line in lines:
        out.append(line)
        total += len(line) + 1
        if total > MAX_CHARS:
            break
    return "\n".join(out)


def _cell(value) -> str:
    return "" if value is None else re.sub(r"[\t\r\n]+", " ", str(value))


def _xlsx_text(path: Path) -> str:
    from openpyxl import load_workbook  # lazy: optional at runtime

    _zip_guard(path)
    with open(path, "rb") as f:
        wb = load_workbook(f, read_only=True, data_only=True)
        try:
            many = len(wb.sheetnames) > 1

            def lines() -> Iterator[str]:
                if many:  # every name up front, so a long first sheet cannot cut the others out of view
                    yield "--- Sheets: " + " | ".join(wb.sheetnames) + " ---"
                for ws in wb.worksheets:
                    if many:
                        yield f"--- Sheet: {ws.title} ---"
                    for row in ws.iter_rows(values_only=True):
                        yield "\t".join(_cell(c) for c in row)

            return _bounded(lines())
        finally:
            wb.close()


def _pdf_text(path: Path, name: str) -> str:
    import pypdf  # lazy: optional at runtime

    reader = pypdf.PdfReader(path)
    if reader.is_encrypted:
        raise UploadError(f"'{name}' is password-protected.")
    return _bounded(page.extract_text() or "" for page in reader.pages)


def _docx_text(path: Path) -> str:
    import docx  # lazy: optional at runtime (python-docx)

    _zip_guard(path)
    doc = docx.Document(str(path))
    rows = (p.text for p in doc.paragraphs)
    cells = ("\t".join(c.text.strip() for c in r.cells) for t in doc.tables for r in t.rows)
    return _bounded(t for t in (*rows, *cells) if t)


def discard(uploads: Iterable[Upload]) -> None:
    """Remove staged bytes that were never published (a no-op once they were)."""
    for u in uploads:
        if u.staged is not None:
            u.staged.path.unlink(missing_ok=True)


# ── Saving (inside detached._begin's transaction) ─────────────────────────────


def hint(upload_id: int) -> str:
    """The trusted line before a kept table's block: only the id, never the (untrusted) filename."""
    return (
        f"[Upload {upload_id}: a spreadsheet the user attached; the block below is its start. "
        f'Read any rows with core_read_upload(id={upload_id}, range="A1:F200").]'
    )


def save_in(conn: db.Conn, user_id: int, conversation_id: int, message_id: int, content: dict, uploads: list[Upload]):
    """Hold each kept file's blob with a row, rename it into place (under the lock, before COMMIT,
    as files.service does), and store the blocks on the message as `files`."""
    files = []
    for u in uploads:
        entry: dict = {"filename": u.filename, "kind": u.kind, "text": u.text}
        if u.staged is not None:
            files_service.hold_blob_in(conn, u.staged)
            uid = db.insert_in(
                conn,
                """INSERT INTO core_agent_uploads
                   (conversation_id, message_id, user_id, filename, mime_type, kind, byte_size, sha256, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    conversation_id,
                    message_id,
                    user_id,
                    u.filename,
                    u.mime_type,
                    u.kind,
                    u.staged.byte_size,
                    u.staged.sha256,
                    clock.now_iso(),
                ),
            )
            storage.publish(u.staged)
            entry["upload_id"] = uid
            if u.kind == "table":
                entry["text"] = hint(uid) + "\n" + u.text
        files.append(entry)
    conn.execute(
        "UPDATE core_agent_messages SET content = ? WHERE id = ?",
        (json.dumps({**content, "files": files}), message_id),
    )


def image_parts(message_id: int) -> list[dict]:
    """The message's photos as neutral image parts (providers translate them), in upload order."""
    parts = []
    for row in db.rows(
        "SELECT mime_type, sha256 FROM core_agent_uploads WHERE message_id = ? AND kind = 'image' ORDER BY id",
        (message_id,),
    ):
        path = storage.blob_path(row["sha256"])
        if path.is_file():  # a lost blob leaves only the placeholder
            parts.append(
                {
                    "type": "image",
                    "media_type": row["mime_type"],
                    "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                }
            )
    return parts


# ── core_read_upload ──────────────────────────────────────────────────────────


def _col(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _letters(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _bounds(rng) -> tuple[int, int, int | None, int | None]:
    """(first col, first row, last col, last row), 1-based; None is open. A1:F200, A:C, 5:20, B7."""
    text = str(rng or "").strip().upper().replace("$", "")
    if not text:
        return 1, 1, None, None
    m = _RANGE_RE.fullmatch(text)
    single = m is not None and m.group(3) is None and m.group(4) is None
    if m is None or (single and not (m.group(1) and m.group(2))) or text == ":":
        raise Invalid(f"range {rng!r} is not like A1:F200, A:C, 5:20 or B7.")
    c1, r1, c2, r2 = m.groups()
    if single:
        c2, r2 = c1, r1
    first_col, first_row = _col(c1) if c1 else 1, int(r1) if r1 else 1
    last_col, last_row = (_col(c2) if c2 else None), (int(r2) if r2 else None)
    if (
        first_row < 1
        or (last_row is not None and last_row < first_row)
        or (last_col is not None and last_col < first_col)
    ):
        raise Invalid(f"range {rng!r} is empty.")
    return first_col, first_row, last_col, last_row


def _csv_rows(path: Path, name: str) -> Iterator[list[str]]:
    text = _decode(path.read_bytes(), name)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    yield from csv.reader(io.StringIO(text), dialect)


def read(user, args: dict) -> str:
    """Rows of a kept CSV or XLSX, `range` within `sheet`, as numbered tab-separated lines."""
    try:
        upload_id = int(str(args.get("id")))
    except (TypeError, ValueError):
        raise NotFound(NOT_FOUND) from None
    row = db.one("SELECT * FROM core_agent_uploads WHERE id = ?", (upload_id,))
    if (
        row is None
        or row["user_id"] != user.id
        or row["conversation_id"] != calling_conversation.get()
        or row["kind"] != "table"
    ):
        raise NotFound(NOT_FOUND)
    path = storage.blob_path(row["sha256"])
    if not path.is_file():
        raise NotFound(NOT_FOUND)
    c1, r1, c2, r2 = _bounds(args.get("range"))
    lines: list[str] = []
    size, last, more = 0, r1 - 1, False

    def page(rows: Iterable, start: int) -> None:
        nonlocal size, last, more
        for n, cells in enumerate(rows, start):
            if n < r1:
                continue
            if r2 is not None and n > r2:
                return
            line = f"{n}\t" + "\t".join(_cell(c) for c in list(cells)[c1 - 1 : c2])
            if not lines and len(line) > READ_CHARS:  # one row over a page: show its start, then move on
                line = line[:READ_CHARS] + f" …[row cut at {READ_CHARS:,} characters]"
            elif len(lines) >= READ_ROWS or size + len(line) > READ_CHARS:
                more = True
                return
            lines.append(line)
            size, last = size + len(line) + 1, n

    if row["filename"].lower().endswith(".xlsx"):
        from openpyxl import load_workbook

        with open(path, "rb") as f:
            wb = load_workbook(f, read_only=True, data_only=True)
            try:
                sheet = args.get("sheet")
                if sheet and sheet not in wb.sheetnames:
                    # the names are the file's own text, so they come back fenced, never in an error
                    names = delimiters.wrap_untrusted_upload(row["filename"], "\n".join(wb.sheetnames))
                    return f"[Upload {upload_id}: no sheet by that name; its sheets are listed below.]\n{names}"
                ws = wb[sheet] if sheet else wb.worksheets[0]
                page(ws.iter_rows(min_row=r1, max_row=r2, values_only=True), r1)
            finally:
                wb.close()
    else:
        page(_csv_rows(path, row["filename"]), 1)
    cols = _letters(c1) + (f"-{_letters(c2)}" if c2 != c1 else "") if c2 else f"{_letters(c1)} onward"
    if not lines:
        note = f"[Upload {upload_id}: no rows in that range.]"
    elif more:
        rest = f"{_letters(c1) if c1 > 1 or c2 else ''}{last + 1}:{_letters(c2) if c2 else ''}{r2 or ''}"
        note = (
            f'[Upload {upload_id}: rows {r1}-{last}, columns {cols}; more rows follow, continue with range="{rest}".]'
        )
    else:
        note = f"[Upload {upload_id}: rows {r1}-{last}, columns {cols}; end of the range.]"
    body = "\n".join(lines) or "(empty)"
    return note + "\n" + delimiters.wrap_untrusted_upload(row["filename"], body)
