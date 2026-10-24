"""Response models for a record's timeline."""

from typing import Any, Literal

from backend.core.platform.models import Out, UserRef


class FieldChange(Out):
    field: str
    old: Any
    new: Any


class TimelineEntry(Out):
    """`changes` lists the changed fields of a `field_change` entry and is None otherwise."""

    id: int
    kind: Literal["note", "comment", "field_change", "system"]
    body: str
    changes: list[FieldChange] | None
    author: UserRef | None
    created_at: str
