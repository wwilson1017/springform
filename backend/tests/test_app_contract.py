"""The app contract (docs/agents/apps-and-contracts.md), checked for every installed app and
falsified against fixtures/bad_app, which breaks each rule once."""

import ast
import importlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.core import db as core_db, entities, registry
from backend.core.auth.deps import require_roles
from backend.core.registry import AppContractError, AppManifest

FIXTURES = Path(__file__).parent / "fixtures"
INSTALLED = core_db.app_dirs(core_db.APPS_DIR)
_SQLITE_INTERNAL = re.compile(r"^(sqlite_autoindex_|sqlite_sequence$|sqlite_stat\d)")
_FTS_SHADOW = ("_data", "_idx", "_content", "_docsize", "_config")


def _schema(data_dir: Path, app_dirs: list[Path]) -> list[dict]:
    core_db.init(data_dir)
    try:
        core_db.migrate(app_dirs)
        objects = core_db.rows("SELECT type, name, tbl_name, sql FROM sqlite_master")
        for o in objects:
            o["fks"] = [r["table"] for r in core_db.rows(f"PRAGMA foreign_key_list('{o['name']}')")] if o["type"] == "table" else []
            o["columns"] = {r["name"] for r in core_db.rows(f"PRAGMA table_info('{o['name']}')")} if o["type"] == "table" else set()
        return objects
    finally:
        core_db.close()


def _cross_app_imports(app_dir: Path, slug: str) -> list[str]:
    found = []
    for path in app_dir.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom):
                if node.level > 1:
                    found.append(f"{path.name}: relative import leaves the app package")
                names = [node.module or ""]
            for name in names:
                parts = name.split(".")
                if parts[:2] == ["backend", "apps"] and len(parts) > 2 and parts[2] != slug and parts[3:] != ["api"]:
                    found.append(f"{path.name}: imports {name}; other apps are reachable only through <app>.api")
    return found


def contract_problems(app_dir: Path, tmp_path: Path) -> list[str]:
    slug, p = app_dir.name, []
    raw = json.loads((app_dir / "app.json").read_text(encoding="utf-8"))
    try:
        manifest = registry.load_manifest(app_dir)
    except ValidationError as e:
        p += [f"manifest: {'.'.join(map(str, err['loc'])) or 'app.json'}: {err['msg']}" for err in e.errors()]
        manifest = None
    except AppContractError as e:
        p.append(f"manifest: {e}")
        manifest = None

    for f in ("router.py", "seed.py", manifest.docs if manifest else "docs/index.md"):
        if not (app_dir / f).is_file():
            p.append(f"missing {f}")
    migrations = sorted((app_dir / "migrations").glob("*.sql"))
    if not migrations:
        p.append("missing migrations/*.sql")
    for m in migrations:
        if not re.match(rf"^\d{{14}}_{slug}_\w+\.sql$", m.name):
            p.append(f"migration {m.name} must be named <timestamp>_{slug}_<name>.sql")
        if m.name[:14] < "20261101000000":
            p.append(f"migration {m.name}: app migrations are stamped 20261101000000 or later")

    package = registry.package_for(app_dir)
    mods = {n: importlib.import_module(f"{package}.{n}") for n in registry.MODULES if (app_dir / f"{n}.py").is_file()}

    # Ownership by name prefix, for every object the app's migrations create.
    core_names = {o["name"] for o in _schema(tmp_path / "core-only", [])}
    objects = _schema(tmp_path / slug, [app_dir])
    virtual = {o["name"] for o in objects if (o["sql"] or "").upper().startswith("CREATE VIRTUAL")}

    def owner(name: str) -> str | None:
        if name == "_migrations_applied" or _SQLITE_INTERNAL.match(name):
            return "sqlite"
        for v in virtual:
            if name.startswith(v) and name[len(v):] in _FTS_SHADOW:
                return owner(v)
        if name.startswith("core_"):
            return "core"
        return slug if name.startswith(f"{slug}_") else None

    owned_tables = set()
    for o in objects:
        if o["name"] in core_names:
            continue
        own = owner(o["name"])
        if own != slug:
            p.append(f"{o['type']} {o['name']!r} is not named {slug}_*")
            continue
        if o["type"] in ("index", "trigger") and owner(o["tbl_name"]) != slug:
            p.append(f"{o['type']} {o['name']!r} targets {o['tbl_name']!r}, which {slug} does not own")
        if o["type"] == "view":
            for t in re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_]\w*)", o["sql"], re.IGNORECASE):
                if owner(t) not in (slug, "core"):
                    p.append(f"view {o['name']!r} reads {t!r}")
        if o["type"] == "table" and o["name"] not in virtual and not o["name"].endswith(_FTS_SHADOW):
            owned_tables.add(o["name"])
        for target in o["fks"]:
            if owner(target) not in (slug, "core"):
                p.append(f"table {o['name']!r} REFERENCES {target!r}; only {slug}_* and core_* tables may be referenced")
    columns = {o["name"]: o["columns"] for o in objects}

    entity_types = set()
    for e in getattr(mods.get("entities"), "ENTITIES", []):
        entity_types.add(e.type)
        if not e.type.startswith(f"{slug}.") or e.table not in owned_tables:
            p.append(f"entity {e.type!r} on {e.table!r} must be {slug}.<name> on a table {slug} owns")

    seed = mods.get("seed")
    if seed is not None:
        for name in ("seed", "sample", "RESET_TABLES"):
            if not hasattr(seed, name):
                p.append(f"seed.py must export {name}")
        reset = set(getattr(seed, "RESET_TABLES", []))
        if reset != owned_tables:
            p.append(f"RESET_TABLES {sorted(reset)} must equal the owned tables {sorted(owned_tables)}")
        for table, spec in getattr(seed, "EXPORT", {}).items():
            if table not in owned_tables:
                p.append(f"EXPORT names {table!r}, which {slug} does not own")
            elif missing := set(spec.get("columns", [])) - columns[table]:
                p.append(f"EXPORT {table!r} names columns that do not exist: {sorted(missing)}")
            if "entity" not in spec:
                p.append(f"EXPORT {table!r} needs an entity (an entity type of {slug}, or None)")
            elif spec["entity"] is not None and spec["entity"] not in entity_types:
                p.append(f"EXPORT {table!r} names entity {spec['entity']!r}, which {slug} does not register")
            for key in ("id_column", "owner_column"):  # optional keys that name a column of the table
                if key in spec and spec[key] not in columns.get(table, set()):
                    p.append(f"EXPORT {table!r} {key} {spec[key]!r} is not a column")

    for job in getattr(mods.get("jobs"), "JOBS", []):
        if not job.name.startswith(f"{slug}."):
            p.append(f"job {job.name!r} must be named {slug}.<job>")
    for tool in mods["tools"].get_tools() if "tools" in mods else []:
        if not tool.name.startswith(f"{slug}_"):
            p.append(f"tool {tool.name!r} must be named {slug}_<tool>")
    for hook in getattr(mods.get("hooks"), "HOOKS", {}):
        if hook not in entities.HOOKS:
            p.append(f"unknown hook {hook!r}")
    for key in getattr(mods.get("settings"), "DEFAULTS", {}):
        if not key.startswith(f"{slug}."):
            p.append(f"setting {key!r} must be named {slug}.<key>")
    for name in raw.get("publishes", []):
        for fn in (name, f"{name}_in"):
            if not hasattr(mods.get("api"), fn):
                p.append(f"publishes {name!r} but api.py has no {fn}")
    p += _cross_app_imports(app_dir, slug)
    return p


@pytest.mark.parametrize("app_dir", INSTALLED, ids=[d.name for d in INSTALLED])
def test_installed_app_meets_the_contract(app_dir, tmp_path):
    assert contract_problems(app_dir, tmp_path) == []


def test_bad_app_breaks_every_rule(tmp_path):
    problems = "\n".join(contract_problems(FIXTURES / "bad_app", tmp_path))
    expected = [
        r"manifest: .*slug 'api' is reserved",
        r"manifest: .*roles",
        r"manifest: .*not a version",
        r"manifest: name: ",
        r"manifest: colour: ",  # unknown keys are refused
        r"missing router\.py",
        r"missing docs/index\.md",
        r"migration 20261001000000_other_thing\.sql must be named",
        r"migration 20261001000000_other_thing\.sql: app migrations are stamped",
        r"table 'widgets' is not named bad_app_\*",
        r"table 'core_hack' is not named bad_app_\*",
        r"index 'bad_app_users_name' targets 'core_users'",
        r"view 'bad_app_peek' reads 'example_widgets'",
        r"table 'bad_app_things' REFERENCES 'example_widgets'",
        r"entity 'example\.thing'",
        r"seed\.py must export seed",
        r"seed\.py must export sample",
        r"RESET_TABLES .* must equal",
        r"EXPORT names 'core_users'",
        r"EXPORT 'bad_app_things' names columns that do not exist: \['nope'\]",
        r"EXPORT 'bad_app_things' names entity 'bad_app\.nothing'",
        r"EXPORT 'bad_app_things' id_column 'thing_ref' is not a column",
        r"EXPORT 'bad_app_things' owner_column 'owner' is not a column",
        r"job 'tidy' must be named bad_app\.<job>",
        r"tool 'make_thing' must be named bad_app_<tool>",
        r"unknown hook 'on_saved'",
        r"setting 'color' must be named bad_app\.<key>",
        r"publishes 'get_thing' but api\.py has no get_thing_in",
        r"service\.py: imports backend\.apps\.example\.service",
    ]
    for pattern in expected:
        assert re.search(pattern, problems), f"rule not caught: {pattern}\n---\n{problems}"


def _manifest(**overrides) -> dict:
    return {"slug": "widgets", "name": "Widgets", "path": "/widgets", "roles": ["member"],
            "version": "0.1.0", "requires_core": ">=0.1,<1", **overrides}


@pytest.mark.parametrize("overrides, message", [
    ({"slug": "Widgets", "path": "/Widgets"}, "pattern"),
    ({"slug": "auth", "path": "/auth"}, "reserved"),
    ({"slug": "people", "path": "/people"}, "reserved"),
    ({"slug": "core_tools", "path": "/core_tools"}, "core_"),
    ({"path": "/other"}, "path must be '/widgets'"),
    ({"roles": ["admin", "owner"]}, "roles"),
    ({"roles": []}, "roles"),
    ({"requires_core": "0.1"}, "requires_core"),
    ({"badge": "/api/other/badge"}, "badge"),
])
def test_manifest_rules(overrides, message):
    with pytest.raises(ValidationError, match=message):
        AppManifest.model_validate(_manifest(**overrides))


def test_slug_must_equal_its_folder(tmp_path):
    (tmp_path / "gadgets").mkdir()
    (tmp_path / "gadgets" / "app.json").write_text(json.dumps(_manifest()))
    with pytest.raises(AppContractError, match="must match"):
        registry.load_manifest(tmp_path / "gadgets")


def test_core_migrations_reference_only_core(tmp_path):
    for o in _schema(tmp_path / "core", []):
        assert o["name"].startswith("core_") or o["name"] == "_migrations_applied" or _SQLITE_INTERNAL.match(o["name"])
        assert all(t.startswith("core_") for t in o["fks"]), o["name"]


# The only /api routes that answer without a session; every other one, core and app, must 401.
# Sign-in flows from the login package; /api/auth/google/stub is out of the schema (PREVIEW_MODE only).
ALLOW_UNAUTHENTICATED = {
    "GET /api/health",
    "GET /api/auth/status", "POST /api/auth/setup", "POST /api/auth/login", "POST /api/auth/login/totp",
    "POST /api/auth/logout", "POST /api/auth/preview",
    "GET /api/auth/google/start", "GET /api/auth/google/callback",
    "GET /api/auth/invite/{token}", "POST /api/auth/invite/{token}", "POST /api/auth/forgot", "POST /api/auth/reset",
}


def anonymous_reachable(fastapi_app: FastAPI, slug: str | None = None) -> list[str]:
    """/api routes (only `/api/<slug>/` when given) outside ALLOW_UNAUTHENTICATED that answer
    something other than 401 without a session."""
    prefix = f"/api/{slug}/" if slug else "/api/"
    client, found = TestClient(fastapi_app), []
    for path, ops in fastapi_app.openapi()["paths"].items():
        for method in ops:
            route = f"{method.upper()} {path}"
            if path.startswith(prefix) and route not in ALLOW_UNAUTHENTICATED:
                status = client.request(method.upper(), re.sub(r"\{[^}]+\}", "1", path)).status_code
                if status != 401:
                    found.append(f"{route} -> {status}")
    return found


def test_every_api_route_needs_a_session_unless_allow_listed(app):
    assert anonymous_reachable(app) == []
    routes = {f"{m.upper()} {p}" for p, ops in app.openapi()["paths"].items() for m in ops}
    assert ALLOW_UNAUTHENTICATED <= routes, f"stale entries: {sorted(ALLOW_UNAUTHENTICATED - routes)}"


def test_guard_check_catches_an_unguarded_route(db):
    router = APIRouter()

    @router.get("/open")
    def open_route() -> dict:
        return {}

    bare = FastAPI()
    bare.include_router(router, prefix="/api/demo")
    assert anonymous_reachable(bare) == ["GET /api/demo/open -> 200"]

    guarded = FastAPI()
    guarded.include_router(router, prefix="/api/demo", dependencies=[Depends(require_roles(["member"]))])
    assert anonymous_reachable(guarded) == []


def test_no_slug_extends_another_slugs_prefix():
    registry.check_slug_prefixes([d.name for d in INSTALLED])
    with pytest.raises(AppContractError, match="start with 'shop_'"):
        registry.check_slug_prefixes(["shop", "shop_extras"])


def test_publishes_is_checked_at_boot(tmp_path):
    manifest = AppManifest.model_validate(_manifest(publishes=["get_widget"]))
    api = SimpleNamespace(get_widget=lambda: None)  # no get_widget_in
    with pytest.raises(AppContractError, match="no get_widget_in"):
        registry.mount_app(FastAPI(), registry.App(manifest, tmp_path, {"router": SimpleNamespace(router=APIRouter()), "api": api}))
