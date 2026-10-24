from backend.core.reminders.service import on_entity_deleted_in, on_entity_merged_in

HOOKS = {"on_entity_deleted": [on_entity_deleted_in], "on_entity_merged": [on_entity_merged_in]}
