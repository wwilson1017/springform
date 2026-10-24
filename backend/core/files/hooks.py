from backend.core.files import service

HOOKS = {
    "on_entity_deleted": [service.on_entity_deleted_in],
    "on_entity_merged": [service.on_entity_merged_in],
}
