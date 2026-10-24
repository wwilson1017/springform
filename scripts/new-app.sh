#!/usr/bin/env bash
# Scaffold a new app that passes the app contract: scripts/new-app.sh <slug> "<Name>"
#
# Writes backend/apps/<slug>/ (manifest, router, api, entities, seed, settings, a migration, docs)
# and frontend/src/apps/<slug>/{contributions.ts,index.tsx}. Then: uv run pytest backend/tests/test_app_contract.py
set -euo pipefail

usage() { echo "usage: scripts/new-app.sh <slug> \"<Name>\"" >&2; exit 2; }
[ $# -eq 2 ] || usage
slug=$1
name=$2
root=$(cd "$(dirname "$0")/.." && pwd)

[[ $slug =~ ^[a-z][a-z0-9_]{1,29}$ ]] || { echo "slug must match ^[a-z][a-z0-9_]{1,29}\$ (it becomes the table prefix)" >&2; exit 1; }
case " core api auth mcp up assets " in *" $slug "*) echo "slug '$slug' is reserved" >&2; exit 1;; esac
[[ $name =~ ^[A-Za-z0-9][A-Za-z0-9\ -]{0,39}$ ]] || { echo "name: letters, digits, spaces and hyphens, up to 40" >&2; exit 1; }
backend="$root/backend/apps/$slug"
frontend="$root/frontend/src/apps/$slug"
[ ! -e "$backend" ] && [ ! -e "$frontend" ] || { echo "app '$slug' already exists" >&2; exit 1; }

# App migrations are stamped 20261101000000 or later.
stamp=$(date -u +%Y%m%d%H%M%S)
[ "$stamp" -ge 20261101000000 ] || stamp=20261101000000

mkdir -p "$backend/migrations" "$backend/docs" "$frontend"
touch "$backend/__init__.py"

cat > "$backend/app.json" <<EOF
{
  "slug": "$slug",
  "name": "$name",
  "description": "",
  "path": "/$slug",
  "icon": "box",
  "roles": ["admin", "member"],
  "order": 500,
  "docs": "docs/index.md",
  "version": "0.1.0",
  "requires_core": ">=0.1,<1",
  "settings_cards": [],
  "sheets": [],
  "publishes": ["get_item"]
}
EOF

cat > "$backend/migrations/${stamp}_${slug}_init.sql" <<EOF
CREATE TABLE ${slug}_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL REFERENCES core_users(id),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
EOF

cat > "$backend/api.py" <<EOF
"""Published functions: the only module other apps may import. Each has an \`_in(conn, …)\` form."""

from backend.core import clock, db, entities

ENTITY = "$slug.item"
COLUMNS = "id, name, owner_user_id, created_at, updated_at"


def list_items(user) -> list[dict]:
    return db.rows(f"SELECT {COLUMNS} FROM ${slug}_items ORDER BY id")


def get_item_in(conn, user, item_id: int) -> dict:
    entities.authorize(user, conn, ENTITY, item_id, "read")
    return dict(conn.execute(f"SELECT {COLUMNS} FROM ${slug}_items WHERE id = ?", (item_id,)).fetchone())


def get_item(user, item_id: int) -> dict:
    return get_item_in(db.get_conn(), user, item_id)


def create_item_in(conn, user, name: str) -> dict:
    now = clock.now_iso()
    cur = conn.execute(
        "INSERT INTO ${slug}_items (name, owner_user_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (name, user.id, now, now),
    )
    return get_item_in(conn, user, cur.lastrowid)


def create_item(user, name: str) -> dict:
    with db.transaction() as conn:
        return create_item_in(conn, user, name)
EOF

cat > "$backend/router.py" <<EOF
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.apps.$slug import api
from backend.core.auth.deps import User, current_user

router = APIRouter()


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.get("/items")
def list_items(user: User = Depends(current_user)) -> list[dict]:
    return api.list_items(user)


@router.post("/items")
def create_item(body: ItemIn, user: User = Depends(current_user)) -> dict:
    return api.create_item(user, body.name)


@router.get("/items/{item_id}")
def get_item(item_id: int, user: User = Depends(current_user)) -> dict:
    return api.get_item(user, item_id)
EOF

cat > "$backend/entities.py" <<EOF
from backend.core.entities import Entity, title_from

# can_read / can_write default to "any active member"; pass your own to restrict.
ENTITIES = [
    Entity(
        type="$slug.item", table="${slug}_items", label="Item", label_plural="Items",
        url_fn=lambda item_id: f"/$slug/items/{item_id}", title_fn=title_from("${slug}_items"),
    ),
]
EOF

cat > "$backend/seed.py" <<EOF
RESET_TABLES = ["${slug}_items"]  # every real table the app owns, in creation order
EXPORT = {
    "${slug}_items": {"entity": "$slug.item", "columns": ["id", "name", "owner_user_id", "created_at", "updated_at"]},
}


def seed(conn) -> None:
    """Data every install needs; runs on each boot, so keep it idempotent."""


def sample(conn) -> None:
    """Demo data for PREVIEW_MODE."""
EOF

cat > "$backend/settings.py" <<EOF
DEFAULTS: dict = {}  # keys are named "$slug.<key>"
EOF

cat > "$backend/docs/index.md" <<EOF
# $name

What this app is for, written for the people who use it.
EOF

cat > "$frontend/contributions.ts" <<EOF
import type { AppContributions } from '../../core/apps/types';

// Loaded eagerly into the shell: lazy loaders and plain data only, never a static screen import.
export default {
  slug: '$slug',
} satisfies AppContributions;
EOF

cat > "$frontend/index.tsx" <<EOF
import type { AppModule } from '../../core/apps/types';

/** Mounted by Root under \`/$slug/*\`, so routes in here are relative to it. */
// eslint-disable-next-line react-refresh/only-export-components -- the contract is a default-exported { slug, App }
function App() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-8 md:px-8">
      <h1 className="m-0 font-display text-2xl text-sf-ink">$name</h1>
    </div>
  );
}

export default { slug: '$slug', App } satisfies AppModule;
EOF

echo "Created backend/apps/$slug and frontend/src/apps/$slug."
echo "Check it: uv run pytest backend/tests/test_app_contract.py"
