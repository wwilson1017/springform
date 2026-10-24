from pydantic import BaseModel, ConfigDict, Field


class WidgetIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    color: str | None = Field(default=None, max_length=50)
    is_private: bool = False
    person_id: int | None = None


class WidgetPatch(BaseModel):
    """Only the fields sent are changed; person_id and color may be set to null."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    color: str | None = Field(default=None, max_length=50)
    is_private: bool | None = None
    person_id: int | None = None


class Widget(BaseModel):
    id: int
    name: str
    color: str | None
    owner_user_id: int
    person_id: int | None
    is_private: bool
    created_at: str
    updated_at: str
