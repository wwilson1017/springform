"""The Guide library: committed Markdown read from disk once, then searched without an index.

Topics come from `backend/core/docs/*.md` (app "core") and every installed app's `docs/*.md`.
Slugs: a core file's name (`getting-started`); an app's `index.md` is the app's slug (`example`),
its other files `<slug>.<name>` (`example.widgets`).

Each file opens with front matter (hand-parsed; three keys):

    ---
    title: Getting started        (required, at most 80 characters)
    summary: One line for lists   (optional, at most 200)
    order: 10                     (optional integer; lower sorts first, default 1000)
    ---

A body over MAX_TOPIC_CHARS, an unknown key, a bad file name or a duplicate slug makes a topic
bad. `load(strict=True)` raises on it, so a test (and a fork's CI) fails loudly; at runtime
`topics()` loads with strict=False, logging and skipping a bad topic so one broken doc never takes
the Guide down. Content is immutable per deploy, so one cache and no invalidation.

Search is a deterministic ranking pass: title beats summary beats body, ties break on slug.
"""

from __future__ import annotations

import functools
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from backend.core import registry

logger = logging.getLogger(__name__)

CORE_DOCS = Path(__file__).resolve().parents[1] / "docs"
MAX_TOPIC_CHARS = 8000
MAX_TITLE_CHARS = 80
MAX_SUMMARY_CHARS = 200
DEFAULT_ORDER = 1000
_STEM = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_KEYS = {"title", "summary", "order"}


class GuideError(Exception):
    """A malformed topic file or corpus."""


@dataclass(frozen=True)
class Topic:
    slug: str
    app: str  # "core" or the owning app's slug
    title: str
    summary: str
    order: int
    body: str  # Markdown, front matter stripped


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise GuideError("missing front matter: the file must open with '---'")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise GuideError("unterminated front matter: no closing '---'") from None
    meta: dict[str, str] = {}
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        key, sep, value = raw.partition(":")
        if not sep:
            raise GuideError(f"front-matter line is not 'key: value': {raw!r}")
        if key.strip() in meta:
            raise GuideError(f"duplicate front-matter key: {key.strip()!r}")
        meta[key.strip()] = value.strip()
    return meta, "\n".join(lines[end + 1 :]).strip()


def parse_topic(slug: str, app: str, text: str) -> Topic:
    meta, body = parse_front_matter(text)
    if unknown := set(meta) - _KEYS:
        raise GuideError(f"{slug}: unknown front-matter keys {sorted(unknown)}; allowed: title, summary, order")
    title, summary = meta.get("title", ""), meta.get("summary", "")
    if not title or len(title) > MAX_TITLE_CHARS:
        raise GuideError(f"{slug}: title must be 1-{MAX_TITLE_CHARS} characters")
    if len(summary) > MAX_SUMMARY_CHARS:
        raise GuideError(f"{slug}: summary must be at most {MAX_SUMMARY_CHARS} characters")
    try:
        order = int(meta.get("order", DEFAULT_ORDER))
    except ValueError:
        raise GuideError(f"{slug}: order must be a whole number") from None
    if not body:
        raise GuideError(f"{slug}: has no body")
    if len(body) > MAX_TOPIC_CHARS:
        raise GuideError(f"{slug}: body is {len(body)} characters, over the {MAX_TOPIC_CHARS} cap; split it")
    return Topic(slug, app, title, summary, order, body)


def load(sources: tuple[tuple[str, str], ...], *, strict: bool = True) -> tuple[Topic, ...]:
    """Every topic under each `(app, folder)` source, in source order, then (order, slug).
    strict: raise on the first bad topic; otherwise log it and skip it (a duplicate slug keeps
    the topic loaded first, so core wins over an app)."""
    topics: list[Topic] = []
    seen: set[str] = set()
    for app, folder in sources:
        found = []
        for path in sorted(Path(folder).glob("*.md")):
            try:
                if not _STEM.match(path.stem):
                    raise GuideError(f"{path.name}: file names are lowercase words joined by single hyphens")
                slug = path.stem if app == "core" else (app if path.stem == "index" else f"{app}.{path.stem}")
                if slug in seen:
                    raise GuideError(f"{path.name}: duplicate Guide slug {slug!r}")
                found.append(parse_topic(slug, app, path.read_text(encoding="utf-8")))
                seen.add(slug)
            except (GuideError, OSError, UnicodeDecodeError) as e:
                if strict:
                    raise
                logger.warning("Guide skipped %s: %s", path, e)
        topics += sorted(found, key=lambda t: (t.order, t.slug))
    return tuple(topics)


def sources() -> tuple[tuple[str, str], ...]:
    return (("core", str(CORE_DOCS)), *((a.slug, str(a.path / "docs")) for a in registry.installed()))


@functools.lru_cache(maxsize=4)
def _cached(sources_: tuple[tuple[str, str], ...]) -> tuple[Topic, ...]:
    return load(sources_, strict=False)


def topics() -> tuple[Topic, ...]:
    """The installed library, loaded on first use; bad topics are logged and left out."""
    return _cached(sources())


def warm() -> None:
    """Load at startup so the first reader does not pay for it. Never raises; an unexpected
    failure is logged and the routes retry lazily."""
    try:
        count = len(topics())
    except Exception:
        logger.warning("Guide failed to load; it will retry on first use", exc_info=True)
        return
    logger.info("Guide loaded (%d topics)", count)


# ── Search ────────────────────────────────────────────────────────────────────
# Ported from the donor's ranking: word match with a one-letter plural fold, a half-weight prefix
# match on title and summary, a capped body count and a whole-phrase bonus. No stemmer, no index.

MAX_QUERY_CHARS = 200
MAX_QUERY_TOKENS = 12
SNIPPET_CHARS = 220
_W_TITLE, _W_SUMMARY, _W_BODY, _W_PHRASE = 8, 4, 1, 10
_BODY_HITS_CAP = 3  # body hits per word stay below one summary match
_MIN_PREFIX_CHARS = 3
_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an the and or of to in is it for on with my do does did how can what why when where who you your me be am "
    "are was were this that these those from at by as if not no but so there here get got should would could will "
    "shall have has had about into out up down then than too very just i".split()
)


def _fold(token: str) -> str:
    return token[:-1] if len(token) > 3 and token.endswith("s") else token


def _words(text: str) -> list[str]:
    return [_fold(t) for t in _TOKEN.findall(text.lower())]


def tokenize(query: str) -> list[str]:
    """Query words: lowercased, stopwords and single letters dropped, deduplicated, capped."""
    out: list[str] = []
    for raw in _TOKEN.findall(query.lower()[:MAX_QUERY_CHARS]):
        token = _fold(raw)
        if len(raw) < 2 or raw in _STOPWORDS or token in out:
            continue
        out.append(token)
        if len(out) >= MAX_QUERY_TOKENS:
            break
    return out


def score(topic: Topic, tokens: list[str]) -> int:
    fields = ((set(_words(topic.title)), _W_TITLE), (set(_words(topic.summary)), _W_SUMMARY))
    body = _words(topic.body)
    total = 0
    for token in tokens:
        for words, weight in fields:
            if token in words:
                total += weight
            elif len(token) >= _MIN_PREFIX_CHARS and any(w.startswith(token) for w in words):
                total += weight // 2
        total += min(body.count(token), _BODY_HITS_CAP) * _W_BODY
    if len(tokens) > 1 and " ".join(tokens) in " ".join(_words(topic.title)):
        total += _W_PHRASE
    return total


def snippet(topic: Topic, tokens: list[str]) -> str:
    """The paragraph covering the most query words (never the query itself; headings skipped);
    else the summary."""
    best, best_cover = "", 0
    for para in topic.body.split("\n\n"):
        text = " ".join(line.strip() for line in para.splitlines() if line.strip() and not line.startswith("#"))
        cover = sum(1 for token in tokens if token in text.lower())
        if cover > best_cover:
            best, best_cover = text, cover
    text = best if best_cover else (topic.summary or topic.title)
    if len(text) <= SNIPPET_CHARS:
        return text
    head, sep, _ = text[:SNIPPET_CHARS].rpartition(" ")
    return f"{head if sep else text[:SNIPPET_CHARS]}…"


def search(corpus: tuple[Topic, ...] | list[Topic], query: str, limit: int = 10) -> list[tuple[Topic, str]]:
    """`(topic, snippet)` best first; ties break on slug."""
    tokens = tokenize(query)
    if not tokens:
        return []
    scored = [(s, t) for t in corpus if (s := score(t, tokens)) > 0]
    scored.sort(key=lambda pair: (-pair[0], pair[1].slug))
    return [(t, snippet(t, tokens)) for _, t in scored[: max(1, limit)]]
