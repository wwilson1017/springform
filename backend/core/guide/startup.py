from backend.core.guide import library


def on_startup() -> None:
    library.warm()
