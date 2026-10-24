"""Smart import: people from a CSV or vCard file, mapped deterministically when the headers are
recognisable, else by the light model; then created through core's contacts API with their
organizations resolved or created. Ported from CakeCRM's crm/smart_import.py
(docs/PROVENANCE.md).

Contracts still to port (shapes in models.py): `parse(filename, data: bytes) -> ImportParsed`
(the model call, when needed, runs outside any transaction; NoProviderConfigured → 422 asking
for a recognisable CSV), and `confirm(user, people) -> ImportResult` (one transaction,
`contacts.api.create_person_in` + `resolve_or_create_organizations_in` + `link_in`; a row that
fails is skipped with its reason).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.errors import Invalid

if TYPE_CHECKING:
    from backend.core.auth.deps import User

MAX_BYTES = 2 * 1024 * 1024


def parse(user: User, filename: str, data: bytes) -> dict:
    """Placeholder until the smart-import port lands."""
    if len(data) > MAX_BYTES:
        raise Invalid("The file is larger than 2 MB")
    return {"people": [], "method": "csv", "warnings": ["Import is not available yet"]}


def confirm(user: User, people: list[dict]) -> dict:
    """Placeholder until the smart-import port lands."""
    return {"created": 0, "organizations_linked": 0, "skipped": [p["name"] for p in people], "person_ids": []}
