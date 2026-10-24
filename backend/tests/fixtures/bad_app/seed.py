"""Test fixture: no seed()/sample(); RESET_TABLES and EXPORT name tables the app does not own."""

RESET_TABLES = ["bad_app_things", "core_users"]
EXPORT = {
    "core_users": {"entity": "bad_app.thing", "columns": ["password_hash"]},
    "bad_app_things": {"entity": "bad_app.nothing", "columns": ["nope"], "id_column": "thing_ref", "owner_column": "owner"},
}
