"""The two GitHub REST calls Requests needs, with a fine-grained token (Issues: read and write).

Never call these inside `transaction()`. Tests point `transport` at an `httpx.MockTransport`.
"""

from __future__ import annotations

import logging
import threading

import httpx

from backend.core.errors import AppError

logger = logging.getLogger(__name__)

API = "https://api.github.com"
TIMEOUT = 10
PER_PAGE = 100
MAX_PAGES = 10
transport: httpx.BaseTransport | None = None


class GitHubError(AppError):
    status, default = 502, "github_error"


def _client(token: str) -> httpx.Client:
    return httpx.Client(
        base_url=API, transport=transport, timeout=TIMEOUT, follow_redirects=True,
        headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "springform",
        },
    )  # fmt: skip


def _check(response: httpx.Response, ok: int) -> None:
    if response.status_code != ok:
        try:
            message = response.json().get("message", "")
        except ValueError:
            message = ""
        logger.warning(
            "GitHub %s %s -> %s %s", response.request.method, response.request.url, response.status_code, message
        )
        raise GitHubError(f"github_error: {response.status_code} {message}".strip())


def create_issue(repo: str, token: str, title: str, body: str, labels: list[str]) -> dict:
    try:
        with _client(token) as client:
            response = client.post(f"/repos/{repo}/issues", json={"title": title, "body": body, "labels": labels})
    except httpx.HTTPError as e:
        raise GitHubError(f"github_error: {type(e).__name__}") from e
    _check(response, 201)
    return response.json()


def list_issues(repo: str, token: str, label: str, cancel: threading.Event | None = None) -> list[dict]:
    """Every issue (open and closed, pull requests left out) carrying `label`."""
    # simplification: lists every labelled issue on each sync, at most MAX_PAGES * PER_PAGE;
    # upgrade path: pass `since=<last sync>` once a board outgrows that.
    issues: list[dict] = []
    try:
        with _client(token) as client:
            for page in range(1, MAX_PAGES + 1):
                if cancel is not None and cancel.is_set():
                    raise GitHubError("github_error: cancelled")
                response = client.get(
                    f"/repos/{repo}/issues",
                    params={"labels": label, "state": "all", "per_page": PER_PAGE, "page": page},
                )
                _check(response, 200)
                batch = response.json()
                issues += [i for i in batch if "pull_request" not in i]
                if len(batch) < PER_PAGE:
                    break
            else:
                logger.warning(
                    "GitHub %s has over %d '%s' issues; the oldest were not synced", repo, len(issues), label
                )
    except httpx.HTTPError as e:
        raise GitHubError(f"github_error: {type(e).__name__}") from e
    return issues
