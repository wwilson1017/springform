"""The only module other apps may import (`from backend.apps.example.api import …`)."""

from backend.apps.example.service import get_widget, get_widget_in, widgets_for_person, widgets_for_person_in

__all__ = ["get_widget", "get_widget_in", "widgets_for_person", "widgets_for_person_in"]
