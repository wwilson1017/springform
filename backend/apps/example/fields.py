"""Custom fields the app owns: core creates them at boot; an admin may only hide or reorder them."""

from backend.core.fields.api import FieldSpec

FIELDS = [FieldSpec("example.widget", "example_finish", "Finish", "select", options=("Matte", "Gloss"))]
