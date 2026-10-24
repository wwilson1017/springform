"""Keep link tokens out of the access log: a token in `/mcp/<token>` is a credential, so uvicorn's
access line shows `/mcp/***` (after todo-gtd `backend/logscrub.py`, cut to this one path)."""

import logging
import re

_TOKEN_PATH = re.compile(r"(/mcp/)[^/?#\s\"']+")


class ScrubLinkTokens(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):  # uvicorn's access args: (client, method, path, version, status)
            record.args = tuple(_TOKEN_PATH.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args)
        return True


def on_startup() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, ScrubLinkTokens) for f in access.filters):
        access.addFilter(ScrubLinkTokens())
