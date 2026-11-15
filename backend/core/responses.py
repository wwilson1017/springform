"""Response models apps share, so their OpenAPI schema names stay unprefixed."""

from pydantic import BaseModel


class Deleted(BaseModel):
    deleted: int


class Badge(BaseModel):
    count: int
    label: str | None = None
