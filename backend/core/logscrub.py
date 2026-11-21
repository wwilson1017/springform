"""Keep tokens out of the logs (lifted from gtd-suite `backend/logscrub.py`, cut to Springform's paths).

A token in an address is a credential, so its segment is printed as `***`: MCP links
(`/mcp/<token>`, `/link/<token>`, `/<token>/mcp`), invites (`/invite/<token>`, with or without
`/api/auth`) and password resets (`/reset-password/<token>`). A `code`, `state` or `token` query
value (Google's sign-in callback) and a signed URL (`X-Amz-…`, `Signature=`, `sig=`) are masked too.
This covers the app's own output only; a proxy in front (Railway's HTTP log) keeps its own.
"""

import logging
import re
from collections.abc import Mapping

_TOKEN_PATH = re.compile(r"(/(?:mcp|link|invite|reset-password)/)[^/?#\s\"']+")
# /<token>/mcp: only a segment shaped like a link token (43 characters), so the host of a full
# URL ending in /mcp stays readable.
_TOKEN_FIRST = re.compile(r"/[A-Za-z0-9_-]{43}(/mcp(?![\w-]))")
_QUERY_CODE = re.compile(r"([?&](?:code|state|token)=)[^&#\s\"']*", re.I)
_SIGNED_URL = re.compile(r"(?:https?://|/)[^\s\"'<>]*[?&](?:X-Amz-|X-Goog-Signature|Signature=|sig=)[^\s\"'<>]*", re.I)


def scrub(text: str) -> str:
    text = _SIGNED_URL.sub("[signed URL]", text)
    text = _TOKEN_FIRST.sub(r"/***\1", _TOKEN_PATH.sub(r"\1***", text))
    return _QUERY_CODE.sub(r"\1***", text)


def _scrub_arg(arg):
    # Strings and anything that prints a token (a URL object, an exception); an argument with
    # nothing to hide passes through untouched, type and all (uvicorn formats `%d` statuses).
    text = arg if isinstance(arg, str) else str(arg)
    clean = scrub(text)
    return arg if clean == text else clean


class ScrubTokens(logging.Filter):
    """Scrubs the message, its arguments and the rendered traceback."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):  # uvicorn's access args: (client, method, path, version, status)
            record.args = tuple(_scrub_arg(a) for a in record.args)
        elif isinstance(record.args, Mapping):
            record.args = {k: _scrub_arg(v) for k, v in record.args.items()}
        if not isinstance(record.msg, str):
            record.msg = _scrub_arg(record.msg)  # `log.error(exc)`: logging prints str() of it
        elif scrub(record.msg) != record.msg:
            if record.args:
                # The template spells the path and an argument fills in the token ("refused /invite/%s"):
                # scrubbing the template alone would eat the placeholder, so render, then scrub.
                record.msg, record.args = scrub(record.getMessage()), None
            else:
                record.msg = scrub(record.msg)
        if record.exc_info and not record.exc_text:
            # Render the traceback now so every handler's Formatter reuses the scrubbed text.
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = scrub(record.exc_text)
        return True


_LOGGERS = ("uvicorn.access", "uvicorn.error", "uvicorn.asgi", "httpx", "httpcore")


def install() -> None:
    """Scrub every record. A logger's filter sees only records logged on that logger, so the filter
    goes on uvicorn's and httpx's loggers and on the root handlers, which see every record that
    propagates up from `backend.*`. `basicConfig` gives the root a stderr handler at the default
    WARNING level (what Python's last-resort handler printed before), so there is one to filter."""
    logging.basicConfig(format="%(levelname)s:     %(name)s: %(message)s")
    for target in (*logging.getLogger().handlers, *map(logging.getLogger, _LOGGERS)):
        if not any(isinstance(f, ScrubTokens) for f in target.filters):
            target.addFilter(ScrubTokens())
