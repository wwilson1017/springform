"""Tokens never reach a log line: every token path, query code and signed URL is masked, on uvicorn's
access line, in a message template, in an exception's traceback, and on the app's own loggers."""

import logging
import time

from backend.core import logscrub

TOKEN = "a" * 43


def _record(msg, args=None, exc_info=None, name="uvicorn.access"):
    return logging.LogRecord(name, logging.INFO, "", 0, msg, args, exc_info)


def test_access_log_lines_hide_every_token_path():
    for path, shown in (
        ("/mcp/abcDEF123_-xyz?x=1", "/mcp/***?x=1"),
        ("/invite/tok123", "/invite/***"),
        ("/api/auth/invite/tok123", "/api/auth/invite/***"),
        ("/reset-password/tok123", "/reset-password/***"),
        ("/api/auth/google/callback?code=4/abc&state=xyz", "/api/auth/google/callback?code=***&state=***"),
        ("/api/auth/google/start?invite=tok123", "/api/auth/google/start?invite=***"),
    ):
        record = _record('%s - "%s %s HTTP/%s" %d', ("10.0.0.1:5000", "GET", path, "1.1", 200))
        logscrub.ScrubTokens().filter(record)
        assert record.getMessage() == f'10.0.0.1:5000 - "GET {shown} HTTP/1.1" 200'


def test_scrubbed_link_shapes_leave_ordinary_paths_alone():
    assert [
        logscrub.scrub(p)
        for p in (
            f"/link/{TOKEN}",
            f"/{TOKEN}/mcp",
            f"/{TOKEN}/mcp?x=1",
            "/settings/mcp",
            "/api/auth/users/3/resend-invite",
        )
    ] == ["/link/***", "/***/mcp", "/***/mcp?x=1", "/settings/mcp", "/api/auth/users/3/resend-invite"]


def test_signed_urls_are_masked_whole():
    url = "https://bucket.s3.amazonaws.com/f.db?X-Amz-Credential=AK%2F1&X-Amz-Signature=deadbeef"
    assert logscrub.scrub(f"HTTP Request: PUT {url} 200") == "HTTP Request: PUT [signed URL] 200"


def test_a_long_path_scrubs_in_linear_time():
    # Unauthenticated request lines reach the filter on the event loop; a quadratic pattern stalls it.
    started = time.monotonic()
    assert logscrub.scrub("/x" * 20_000) == "/x" * 20_000
    assert time.monotonic() - started < 0.5


def test_a_template_naming_the_path_is_rendered_then_scrubbed():
    record = _record("refused /invite/%s for %s", ("tok123", "x@example.com"), name="backend.core.auth")
    logscrub.ScrubTokens().filter(record)
    assert record.getMessage() == "refused /invite/*** for x@example.com"


def test_a_traceback_naming_a_token_is_scrubbed():
    try:
        raise ValueError("bad link /reset-password/tok123")
    except ValueError as e:
        record = _record("failed", None, (type(e), e, e.__traceback__), name="backend.core.auth")
    logscrub.ScrubTokens().filter(record)
    text = record.exc_text or ""
    assert "tok123" not in text and "/reset-password/***" in text


def test_create_app_filters_uvicorn_and_httpx(app):
    for name in ("uvicorn.access", "uvicorn.error", "httpx"):
        assert sum(isinstance(f, logscrub.ScrubTokens) for f in logging.getLogger(name).filters) == 1


def test_install_filters_each_root_handler_once():
    logscrub.install()
    logscrub.install()
    handlers = logging.getLogger().handlers
    assert handlers and all(sum(isinstance(f, logscrub.ScrubTokens) for f in h.filters) == 1 for h in handlers)
