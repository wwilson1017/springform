"""Bounded list windows, so no caller can ask for an unbounded page. Lists page with `before=<id>`."""

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def limit(value: int | None = None) -> int:
    """`value` clamped to 1..MAX_LIMIT; DEFAULT_LIMIT when not given."""
    return DEFAULT_LIMIT if value is None else max(1, min(int(value), MAX_LIMIT))
