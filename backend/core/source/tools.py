"""Whisk's code tools: search, list and read this install's own source, the copy that ships in the
image (`Dockerfile`), so the answer matches what is deployed, upstream or fork. No network, no key.

Only an allow-list is readable: `READABLE_DIRS` and the top-level `TOP_FILES` and `*.md`. Dotfiles
and dot-folders (`.env`, `.git`, `.venv`), `__pycache__`, `node_modules` and SQLite files are never
read, and a path that resolves outside the root (`..`, an absolute path, a symlink) is refused.
App and core user docs (`backend/**/docs/*.md`) are inside the allow-list, so these tools answer
how-to questions too. Trusted, install-shared reads: offered to admins and members (their check-ins included) and
over MCP.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from backend.core import REPO_ROOT
from backend.core.agent.spec import ToolSpec
from backend.core.errors import Invalid
from backend.core.timeline.tools import human

SEARCH, LIST, READ = "core_code_search", "core_code_list", "core_code_read"
ROOT = REPO_ROOT  # tests point this at a tmp tree
READABLE_DIRS = ("backend", "frontend/src", "docs", "scripts")
TOP_FILES = frozenset({"pyproject.toml", "springform-version", "Dockerfile", "fork-allow.txt"})
SKIP_PARTS = frozenset({"__pycache__", "node_modules"})
MAX_FILE_BYTES = 200_000
MAX_HITS = 50
MAX_HIT_CHARS = 200
MAX_LINES = 400
MAX_READ_CHARS = 40_000


def _clean_parts(rel: PurePosixPath) -> bool:
    return not any(p.startswith(".") or p in SKIP_PARTS or ".sqlite" in p for p in rel.parts)


def _file_ok(rel: PurePosixPath) -> bool:
    if not _clean_parts(rel):
        return False
    if len(rel.parts) == 1:
        return rel.name in TOP_FILES or rel.suffix == ".md"
    s = rel.as_posix()
    return any(s.startswith(d + "/") for d in READABLE_DIRS)


def _dir_ok(rel: PurePosixPath) -> bool:
    """The root, a readable folder, a folder inside one, or a parent on the way to one (`frontend`)."""
    if rel == PurePosixPath("."):
        return True
    s = rel.as_posix()
    return _clean_parts(rel) and any(s == d or s.startswith(d + "/") or d.startswith(s + "/") for d in READABLE_DIRS)


def _resolve(path: str | None) -> tuple[PurePosixPath, Path]:
    """(path relative to the root, real path), or Invalid when it leaves the root."""
    raw = str(path or "").strip()
    if raw.startswith(("/", "~")):
        raise Invalid("path must be relative to the code root, such as backend/core/db.py")
    rel = PurePosixPath(raw.rstrip("/") or ".")
    if ".." in rel.parts:
        raise Invalid("path may not contain '..'")
    root = ROOT.resolve()
    full = (root / rel).resolve()
    if not full.is_relative_to(root):
        raise Invalid("path is outside the code")
    return PurePosixPath(full.relative_to(root).as_posix() or "."), full


def _text(full: Path) -> str | None:
    try:
        if full.stat().st_size > MAX_FILE_BYTES:
            return None
        return full.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _real_ok(full: Path) -> bool:
    """Is the file a link or path ends at readable, inside the root and on the allow-list?"""
    root, real = ROOT.resolve(), full.resolve()
    return real.is_file() and real.is_relative_to(root) and _file_ok(PurePosixPath(real.relative_to(root).as_posix()))


def _files(under: PurePosixPath):
    """Every readable file at or below `under`, as (relative path, real path), sorted."""
    root = ROOT.resolve()
    for dirpath, dirnames, filenames in os.walk(root / under):
        here = PurePosixPath(Path(dirpath).relative_to(root).as_posix())
        dirnames[:] = sorted(d for d in dirnames if _dir_ok(here / d))
        for name in sorted(filenames):
            rel = PurePosixPath(name) if here == PurePosixPath(".") else here / name
            full = Path(dirpath) / name
            if _file_ok(rel) and _real_ok(full):
                yield rel, full


def search(query: str | None, path: str | None = None) -> dict:
    # simplification: scans the tree on every call (about 900 files); upgrade path: cache the file list.
    needle = str(query or "").strip()
    if not needle:
        raise Invalid("query is required")
    rel, full = _resolve(path)
    if not (_dir_ok(rel) if full.is_dir() else _file_ok(rel)):
        raise Invalid(f"{rel} is not readable code")
    files = _files(rel) if full.is_dir() else [(rel, full)]
    hits, total, low = [], 0, needle.lower()
    for frel, ffull in files:
        text = _text(ffull)
        for n, line in enumerate((text or "").splitlines(), 1):
            if low in line.lower():
                total += 1
                if len(hits) < MAX_HITS:
                    hits.append(f"{frel}:{n}: {line.strip()[:MAX_HIT_CHARS]}")
    out: dict = {"query": needle, "hits": hits, "total": total}
    if total > len(hits):
        out["note"] = f"Showing {len(hits)} of {total} matches; narrow the query or pass path."
    elif not total:
        out["note"] = "No matches. Try a shorter or different word, or list a folder."
    return out


def list_dir(path: str | None = None) -> dict:
    rel, full = _resolve(path)
    if not (full.is_dir() and _dir_ok(rel)):
        raise Invalid(f"{rel} is not a readable folder")
    folders, files = [], []
    for entry in sorted(full.iterdir()):
        erel = PurePosixPath(entry.name) if rel == PurePosixPath(".") else rel / entry.name
        if entry.is_dir() and _dir_ok(erel):
            folders.append(entry.name + "/")
        elif _file_ok(erel) and _real_ok(entry):
            files.append(entry.name)
    return {"path": str(rel), "folders": folders, "files": files}


def read(path: str | None, start_line: int | None = None, end_line: int | None = None) -> dict:
    rel, full = _resolve(path)
    if not (full.is_file() and _file_ok(rel)):
        raise Invalid(f"{rel} is not a readable file")
    text = _text(full)
    if text is None:
        raise Invalid(f"{rel} is not a text file under {MAX_FILE_BYTES:,} bytes")
    lines = text.splitlines()
    try:
        start = max(1, int(start_line or 1))
        end = min(len(lines), int(end_line or start + MAX_LINES - 1), start + MAX_LINES - 1)
    except (TypeError, ValueError):
        raise Invalid("start_line and end_line must be whole numbers") from None
    body, shown = [], start - 1
    for n in range(start, end + 1):
        numbered = f"{n}: {lines[n - 1]}"
        if sum(len(b) + 1 for b in body) + len(numbered) > MAX_READ_CHARS:
            break
        body.append(numbered)
        shown = n
    out: dict = {"path": str(rel), "start_line": start, "end_line": shown, "total_lines": len(lines),
                 "text": "\n".join(body)}  # fmt: skip
    if shown < len(lines):
        out["note"] = f"Showing lines {start}-{shown} of {len(lines)}; pass start_line to read on."
    return out


def get_tools() -> list[ToolSpec]:
    path = {"type": "string", "description": "Relative to the code root, e.g. backend/apps/crm"}
    return [
        ToolSpec(
            name=SEARCH,
            description=(
                "Search this install's own source code and docs (the version that is running) for a word or "
                "phrase, case-insensitive. Returns `path:line: text` hits. Use it to explain how a feature or app "
                "works. For how-to questions look in the docs folders first (backend/core/docs, "
                "backend/apps/<app>/docs); then read the code with core_code_read. Explain in plain words, "
                "not code, unless the user asks for code."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Literal text to find, e.g. 'merge' or 'def create'"},
                    "path": {**path, "description": "Limit to this folder or file, e.g. backend/apps/crm"},
                },
                "required": ["query"],
            },
            writes=False,
            handler=lambda user, args: search(args.get("query"), args.get("path")),
            enabled=human,
        ),
        ToolSpec(
            name=LIST,
            description=(
                "List the folders and files in one folder of this install's source. Empty path is the root; "
                "apps are under backend/apps/ (server) and frontend/src/apps/ (screens)."
            ),
            input_schema={"type": "object", "properties": {"path": path}},
            writes=False,
            handler=lambda user, args: list_dir(args.get("path")),
            enabled=human,
        ),
        ToolSpec(
            name=READ,
            description=(
                f"Read one file of this install's source with line numbers, up to {MAX_LINES} lines at a time. "
                "Pass start_line (and end_line) to read a part, e.g. around a core_code_search hit."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {**path, "description": "The file, e.g. backend/core/contacts/service.py"},
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
                "required": ["path"],
            },
            writes=False,
            handler=lambda user, args: read(args.get("path"), args.get("start_line"), args.get("end_line")),
            enabled=human,
        ),
    ]
