"""Keep link tokens out of the access log: a token in a link path is a credential, so uvicorn's
access line shows `/mcp/***`, `/link/***` or `/***/mcp` (after todo-gtd `backend/logscrub.py`,
cut to these paths)."""

import logging
import re

_TOKEN_PATH = re.compile(r"(/mcp/|/link/)[^/?#\s\"']+")
_TOKEN_FIRST = re.compile(r"^/[A-Za-z0-9_-]{43}(?=/mcp(?:[/?#]|$))")


def scrub(path: str) -> str:
    return _TOKEN_FIRST.sub("/***", _TOKEN_PATH.sub(r"\1***", path))


class ScrubLinkTokens(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):  # uvicorn's access args: (client, method, path, version, status)
            record.args = tuple(scrub(a) if isinstance(a, str) else a for a in record.args)
        return True


def on_startup() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, ScrubLinkTokens) for f in access.filters):
        access.addFilter(ScrubLinkTokens())
