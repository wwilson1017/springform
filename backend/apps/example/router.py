from fastapi import APIRouter, Depends

from backend.apps.example import service
from backend.apps.example.models import Widget, WidgetIn, WidgetPatch
from backend.core.auth.deps import User, current_user

router = APIRouter()


@router.get("/widgets", response_model=list[Widget])
def list_widgets(person_id: int | None = None, user: User = Depends(current_user)) -> list[dict]:
    """Readable widgets; `?person_id=` narrows to one person's (the person page's panel)."""
    if person_id is not None:
        return service.widgets_for_person(user, person_id)
    return service.list_widgets(user)


@router.post("/widgets", response_model=Widget)
def create_widget(body: WidgetIn, user: User = Depends(current_user)) -> dict:
    return service.create_widget(user, body)


@router.get("/widgets/{widget_id}", response_model=Widget)
def get_widget(widget_id: int, user: User = Depends(current_user)) -> dict:
    return service.get_widget(user, widget_id)


@router.patch("/widgets/{widget_id}", response_model=Widget)
def update_widget(widget_id: int, body: WidgetPatch, user: User = Depends(current_user)) -> dict:
    return service.update_widget(user, widget_id, body)


@router.get("/badge")
def badge(user: User = Depends(current_user)) -> dict:
    return service.badge(user)
