"""Response models for custom field definitions. Values stay a free-form `{key: value}` map."""

from typing import Literal

from backend.core.platform.models import Out


class FieldDefinition(Out):
    """`options` only for select and multiselect; `required` is advisory (shown, not enforced)."""

    id: int
    entity_type: str
    key: str
    label: str
    type: Literal["text", "number", "boolean", "date", "select", "multiselect", "url", "user"]
    options: list[str] | None
    required: bool
    position: int
    archived_at: str | None
    created_at: str
    updated_at: str


class FieldEntityType(Out):
    """A registered entity type, for the field-definition picker."""

    type: str
    label: str
    label_plural: str
