"""App discovery and mounting: the app contract (docs/agents/apps-and-contracts.md).

An app is a folder `backend/apps/<slug>/` with an `app.json`. Required: `router.py` (exports
`router`), `migrations/*.sql`, `seed.py`, the manifest's `docs` file. Optional modules, each
exporting one name: `api` (the only module another app may import), `entities` (ENTITIES),
`hooks` (HOOKS), `reports` (REPORTS), `tools` (get_tools()), `jobs` (JOBS), `settings` (DEFAULTS).

`install(app)` registers core's own entities, hooks and jobs, then mounts every discovered app:
its router at `/api/<slug>` behind `require_roles(manifest.roles)`, and its entities, reports
and tools wrapped so they also demand one of the app's roles before the app's own checks.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Literal

from fastapi import Depends, FastAPI
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.core import REPO_ROOT, changelog, db, entities, outbox, scheduler, settings
from backend.core.agent import registry as agent_registry
from backend.core.agent.spec import ToolSpec
from backend.core.auth import service as auth_service
from backend.core.auth.deps import User, has_role, require_roles
from backend.core.errors import Forbidden, NotFound
from backend.core.reports import registry as reports
from backend.core.timeline import service as timeline_service

RESERVED_SLUGS = frozenset(
    {
        "core", "api", "auth", "mcp", "up", "assets", "agent", "me", "health", "settings", "people",
        "organizations", "guide", "requests", "login", "setup", "invite", "changelog", "backups", "jobs",
        "sheets", "notifications", "reminders", "whisk", "files", "timeline", "export",
    }
)  # fmt: skip
MODULES = ("router", "seed", "api", "entities", "hooks", "reports", "tools", "jobs", "settings")

CORE_DIR = Path(__file__).resolve().parent
CORE_MODULES = ("router", "hooks", "jobs", "tools", "startup")


def run_startup_hooks() -> None:
    """`backend/core/<pkg>/startup.py` may export `on_startup()`; called from the lifespan after
    migrations and seeds, inside the process lock, before the scheduler starts."""
    for mods in core_packages().values():
        fn = getattr(mods.get("startup"), "on_startup", None)
        if fn:
            fn()


def core_packages() -> dict[str, dict[str, ModuleType]]:
    """Core packages (`backend/core/<pkg>/`) contribute like apps do: `router.py` (exports `router`,
    included as-is, it sets its own `/api/...` prefix), `hooks.py` (HOOKS), `jobs.py` (JOBS) and
    `tools.py` (get_tools(), names prefixed `core_`). A workstream adds a package and never edits
    this file or main.py."""
    out: dict[str, dict[str, ModuleType]] = {}
    for p in sorted(CORE_DIR.iterdir()):
        if not (p.is_dir() and (p / "__init__.py").is_file()):
            continue
        mods = {
            m: importlib.import_module(f"backend.core.{p.name}.{m}") for m in CORE_MODULES if (p / f"{m}.py").is_file()
        }
        if mods:
            out[p.name] = mods
    return out


class AppContractError(RuntimeError):
    pass


class SettingsCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    title: str
    admin_only: bool = False


class Sheet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    mode: Literal["read", "write"]
    description: str = ""


class AppManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(pattern=r"^[a-z][a-z0-9_]{1,29}$")  # permanent: baked into table names
    name: str = Field(min_length=1)
    description: str = ""
    path: str
    icon: str = "box"
    roles: list[Literal["admin", "member"]] = Field(min_length=1)
    order: int = 500
    badge: str | None = None
    docs: str = "docs/index.md"
    version: str
    requires_core: str
    settings_cards: list[SettingsCard] = []
    sheets: list[Sheet] = []
    publishes: list[str] = []

    @field_validator("slug")
    @classmethod
    def _not_reserved(cls, v: str) -> str:
        if v in RESERVED_SLUGS:
            raise ValueError(f"slug {v!r} is reserved")
        if v.startswith("core_"):
            raise ValueError("slug may not start with 'core_' (core owns that table prefix)")
        return v

    @field_validator("version")
    @classmethod
    def _version(cls, v: str) -> str:
        try:
            Version(v)
        except InvalidVersion:
            raise ValueError(f"version {v!r} is not a version") from None
        return v

    @field_validator("requires_core")
    @classmethod
    def _requires_core(cls, v: str) -> str:
        try:
            SpecifierSet(v)
        except InvalidSpecifier:
            raise ValueError(f"requires_core {v!r} is not a version specifier") from None
        return v

    @model_validator(mode="after")
    def _paths(self) -> AppManifest:
        if self.path != f"/{self.slug}":
            raise ValueError(f"path must be '/{self.slug}'")
        if self.badge is not None and not self.badge.startswith(f"/api/{self.slug}/"):
            raise ValueError(f"badge must be a route under /api/{self.slug}/")
        if len(set(self.roles)) != len(self.roles):
            raise ValueError("roles must not repeat")
        return self


def load_manifest(app_dir: Path) -> AppManifest:
    manifest = AppManifest.model_validate(json.loads((app_dir / "app.json").read_text(encoding="utf-8")))
    if manifest.slug != app_dir.name:
        raise AppContractError(f"App folder {app_dir.name!r} declares slug {manifest.slug!r}; they must match")
    return manifest


@dataclass
class App:
    manifest: AppManifest
    path: Path
    modules: dict[str, ModuleType]

    @property
    def slug(self) -> str:
        return self.manifest.slug


def package_for(app_dir: Path) -> str:
    return ".".join(app_dir.resolve().relative_to(REPO_ROOT).parts)


def discover(apps_dir: Path = db.APPS_DIR) -> list[App]:
    apps = []
    for app_dir in db.app_dirs(apps_dir):
        manifest = load_manifest(app_dir)
        missing = [f for f in ("router.py", "seed.py", manifest.docs) if not (app_dir / f).is_file()]
        if not any((app_dir / "migrations").glob("*.sql")):
            missing.append("migrations/*.sql")
        if missing:
            raise AppContractError(f"App '{manifest.slug}' is missing {', '.join(missing)}")
        package = package_for(app_dir)
        modules = {m: importlib.import_module(f"{package}.{m}") for m in MODULES if (app_dir / f"{m}.py").is_file()}
        apps.append(App(manifest, app_dir, modules))
    check_slug_prefixes([a.slug for a in apps])
    return apps


def check_slug_prefixes(slugs: list[str]) -> None:
    """No slug may be another slug + '_' + anything: table ownership is by name prefix."""
    for slug in slugs:
        if clash := [o for o in slugs if o != slug and o.startswith(f"{slug}_")]:
            raise AppContractError(f"App slug(s) {clash} start with '{slug}_', so table ownership would be ambiguous")


CORE_JOBS = [
    scheduler.Job("core.outbox_drain", outbox.drain, every=30, timeout=outbox.CLAIM_TIMEOUT),
    scheduler.Job("core.job_runs_prune", scheduler.prune_job_runs, every=86400),
    scheduler.Job("core.login_attempts_prune", auth_service.prune_login_attempts, every=3600),
]

_APPS: list[App] = []


def install(fastapi_app: FastAPI, apps_dir: Path = db.APPS_DIR) -> list[App]:
    """Reset every registry, register core, then discover and mount the apps. Called by create_app."""
    entities.clear()
    outbox.clear()
    scheduler.clear()
    reports.clear()
    settings.clear_defaults()
    for entity in entities.CORE_ENTITIES:
        entities.register(entity)
    entities.subscribe("on_entity_deleted", timeline_service.on_entity_deleted_in)
    entities.subscribe("on_entity_deleted", changelog.on_entity_deleted_in)
    entities.subscribe("on_entity_merged", timeline_service.on_entity_merged_in)
    for job in CORE_JOBS:
        scheduler.register(job)
    specs: list[ToolSpec] = []
    for mods in core_packages().values():
        if "router" in mods:
            fastapi_app.include_router(mods["router"].router)
        for hook, fns in getattr(mods.get("hooks"), "HOOKS", {}).items():
            for fn in fns:
                entities.subscribe(hook, fn)
        for job in getattr(mods.get("jobs"), "JOBS", []):
            scheduler.register(job)
        if "tools" in mods:
            specs += [replace(t, app="core") for t in mods["tools"].get_tools()]

    apps = discover(apps_dir)
    for app in apps:
        specs += mount_app(fastapi_app, app)
    agent_registry.set_current(agent_registry.build_registry(specs))
    _APPS[:] = apps
    return apps


def mount_app(fastapi_app: FastAPI, app: App) -> list[ToolSpec]:
    """Mount one app; returns its tool specs (validated together by the caller)."""
    m, mods = app.manifest, app.modules
    roles = tuple(m.roles)
    for name in m.publishes:
        for fn in (name, f"{name}_in"):
            if not callable(getattr(mods.get("api"), fn, None)):
                raise AppContractError(f"App '{m.slug}' publishes {name!r} but api.py has no {fn}")
    fastapi_app.include_router(
        mods["router"].router, prefix=f"/api/{m.slug}", tags=[m.slug], dependencies=[Depends(require_roles(roles))]
    )
    for entity in getattr(mods.get("entities"), "ENTITIES", []):
        if entity.app != m.slug:
            raise AppContractError(f"App '{m.slug}' registers entity {entity.type!r} outside its namespace")
        entities.register(_role_scoped(entity, roles))
    for hook, fns in getattr(mods.get("hooks"), "HOOKS", {}).items():
        for fn in fns:
            entities.subscribe(hook, fn)
    for report in getattr(mods.get("reports"), "REPORTS", []):
        reports.register(replace(report, app=m.slug, roles=roles))
    for job in getattr(mods.get("jobs"), "JOBS", []):
        scheduler.register(replace(job, app=m.slug))
    settings.register_defaults(m.slug, getattr(mods.get("settings"), "DEFAULTS", {}))
    tools = mods["tools"].get_tools() if "tools" in mods else []
    return [replace(t, app=m.slug, revision=m.version, enabled=_role_enabled(t.enabled, roles)) for t in tools]


def _role_scoped(entity: entities.Entity, roles: tuple[str, ...]) -> entities.Entity:
    read, write = entity.can_read, entity.can_write
    return replace(
        entity,
        can_read=lambda user, conn, i: has_role(user, roles, "read") and read(user, conn, i),
        can_write=lambda user, conn, i: has_role(user, roles, "write") and write(user, conn, i),
    )


def _role_enabled(enabled, roles: tuple[str, ...]):
    return lambda user: has_role(user, roles, "read") and enabled(user)


def installed() -> list[App]:
    return list(_APPS)


def get_app(slug: str) -> App:
    for app in _APPS:
        if app.slug == slug:
            return app
    raise NotFound(f"no app {slug!r}")


def list_for_user(user: User) -> list[dict]:
    """The launcher's apps for this user. Admins also get hidden apps, marked hidden."""
    state = {r["slug"]: r for r in db.rows("SELECT slug, hidden, position FROM core_apps_state")}
    out = []
    for app in _APPS:
        m = app.manifest
        hidden = bool(state.get(m.slug, {}).get("hidden"))
        if user.role not in m.roles or (hidden and not user.is_admin):
            continue
        out.append({
            "slug": m.slug, "name": m.name, "description": m.description, "path": m.path, "icon": m.icon,
            "roles": list(m.roles), "order": m.order, "badge": m.badge, "hidden": hidden,
            "settings_cards": [c.model_dump() for c in m.settings_cards if user.is_admin or not c.admin_only],
            "version": m.version, "_position": state.get(m.slug, {}).get("position"),
        })
    out.sort(key=lambda a: (a["_position"] is None, a["_position"] or 0, a["order"], a["slug"]))
    for a in out:
        del a["_position"]
    return out


def seed_apps() -> None:
    """Each app's seed(conn) on boot, one transaction per app; seeds must be idempotent."""
    for app in _APPS:
        with db.transaction() as conn:
            app.modules["seed"].seed(conn)


def reset_app_in(conn: db.Conn, slug: str) -> None:
    """Empty one app. Entity rows go through entities.delete_record_in, so their timeline, files
    and change-log rows go too; then the rest of RESET_TABLES. Never touches sqlite_sequence:
    ids keep climbing, so no old reference can attach to a new record."""
    app = get_app(slug)
    for entity in entities.all_entities():
        if entity.app == slug:
            for (record_id,) in conn.execute(f"SELECT id FROM {entity.table}").fetchall():
                entities.delete_record_in(conn, entity.type, record_id)
    for table in reversed(app.modules["seed"].RESET_TABLES):
        if not table.startswith(f"{slug}_"):
            raise AppContractError(f"App '{slug}' RESET_TABLES names {table!r}, which it does not own")
        conn.execute(f"DELETE FROM {table}")


def _holds_data(conn: db.Conn, caller: User | None) -> bool:
    """Any human account besides the caller, or any row in an app's RESET_TABLES or the contacts directory."""
    others = conn.execute(
        "SELECT 1 FROM core_users WHERE role != 'system' AND id != ? LIMIT 1", (caller.id if caller else -1,)
    ).fetchone()
    tables = ["core_people", "core_organizations"] + [t for a in _APPS for t in a.modules["seed"].RESET_TABLES]
    return others is not None or any(conn.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone() for t in tables)


def factory_reset(caller: User | None = None) -> None:
    """factory_reset_in in its own transaction, then the core startup hooks (preview sample contacts)."""
    with db.transaction() as conn:
        factory_reset_in(conn, caller)
    run_startup_hooks()


def factory_reset_in(conn: db.Conn, caller: User | None = None) -> None:
    """Clear every table and every sequence, then re-seed. Allowed only in PREVIEW_MODE, or when no
    human account but the caller exists and every app table and the contacts directory are empty.
    Core startup hooks open their own transactions, so they run in factory_reset, after COMMIT."""
    if not settings.preview_mode() and _holds_data(conn, caller):
        raise Forbidden("Factory reset is only allowed in preview mode or on an install that holds no data.")
    conn.execute("PRAGMA defer_foreign_keys = ON")
    virtual = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND sql LIKE 'CREATE VIRTUAL%'")}
    shadow = {f"{v}_{s}" for v in virtual for s in ("data", "idx", "content", "docsize", "config")}
    tables = [
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        if not r[0].startswith("sqlite_") and r[0] != "_migrations_applied" and r[0] not in virtual | shadow
    ]
    for table in tables:  # FTS tables follow through their triggers
        conn.execute(f'DELETE FROM "{table}"')
    conn.execute("DELETE FROM sqlite_sequence")
    conn.execute(
        """INSERT INTO core_users (id, email, name, role, password_hash, is_active, created_at, updated_at)
           VALUES (0, 'system@springform.local', 'System', 'system', '!', 1, '2026-10-20T00:00:00Z', '2026-10-20T00:00:00Z')"""
    )
    for app in _APPS:
        app.modules["seed"].seed(conn)
    if settings.preview_mode():
        from backend.core import preview

        preview.seed_in(conn)
