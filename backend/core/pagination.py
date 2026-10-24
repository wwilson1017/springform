"""Bounded list windows, so no route can be asked for an unbounded page."""

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def window(limit: int | None = None, offset: int | None = None) -> tuple[int, int]:
    """`(limit, offset)` clamped to 1..MAX_LIMIT and >= 0."""
    limit = DEFAULT_LIMIT if limit is None else max(1, min(int(limit), MAX_LIMIT))
    return limit, max(0, int(offset or 0))
