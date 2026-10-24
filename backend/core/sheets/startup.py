from backend.core.sheets import service


def on_startup() -> None:
    """Seed core_connected_sheets from every installed manifest's `sheets` (idempotent)."""
    service.seed()
