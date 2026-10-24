"""Test fixture: reaches into another app's internals instead of its api module."""

from backend.apps.example.service import list_widgets  # noqa: F401
