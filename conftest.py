# Loads the shared fixtures and the skip/xfail ban for every test: core's in backend/tests and each app's in
# backend/apps/<slug>/tests. Apps need no conftest of their own.
pytest_plugins = ["backend.testing.fixtures"]
