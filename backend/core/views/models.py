"""Response models for saved views. `payload` is the surface's own JSON, stored as sent."""

from typing import Any

from backend.core.platform.models import Out, UserRef


class SavedView(Out):
    """`version` is the equality token an edit must send back; `can_edit`: owner or admin."""

    id: int
    surface: str
    entity_type: str | None
    name: str
    version: int
    payload: dict[str, Any]
    owner: UserRef
    is_shared: bool
    can_edit: bool
    created_at: str
    updated_at: str
