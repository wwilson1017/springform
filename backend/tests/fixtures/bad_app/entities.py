from backend.core.entities import Entity, title_from

ENTITIES = [
    Entity("example.thing", "example_widgets", "Thing", "Things", lambda i: f"/things/{i}", title_from("example_widgets")),
]
