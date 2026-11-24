from typing import Any

from backend.core.fields.api import FieldSpec

NOT_TEXT: Any = 5

FIELDS = [
    FieldSpec("core.person", "tier", "Tier", "text"),  # key lacks the bad_app_ prefix
    FieldSpec("example.widget", "bad_app_size", "Size", "sizes"),  # another app's entity; unknown type
    FieldSpec("core.person", "bad_app_level", NOT_TEXT, "text"),  # label is not text
    FieldSpec("core.person", "bad_app_tier", "Tier", "select", options=()),  # a select needs options
    FieldSpec("core.person", "bad_app_tier", "Tier again", "text"),  # declared twice
]
