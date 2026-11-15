#!/usr/bin/env bash
# Scaffold a new app that passes the app contract: scripts/new-app.sh <slug> "<Name>"
#
# Writes backend/apps/<slug>/ (manifest, router, models, service, entities, seed, a migration, docs, tests)
# and frontend/src/apps/<slug>/{contributions.ts,index.tsx}. Then: uv run pytest
set -euo pipefail

usage() { echo "usage: scripts/new-app.sh <slug> \"<Name>\"" >&2; exit 2; }
[ $# -eq 2 ] || usage
slug=$1
name=$2
root=$(cd "$(dirname "$0")/.." && pwd)

[[ $slug =~ ^[a-z][a-z0-9_]{1,29}$ ]] || { echo "slug must match ^[a-z][a-z0-9_]{1,29}\$ (it becomes the table prefix)" >&2; exit 1; }
# Keep in step with RESERVED_SLUGS in backend/core/registry.py.
reserved=" core api auth mcp up assets agent me health settings people organizations guide requests login setup invite changelog backups jobs sheets notifications reminders whisk files timeline export "
case "$reserved" in *" $slug "*) echo "slug '$slug' is reserved" >&2; exit 1;; esac
# Table ownership is by name prefix: a slug may not extend core's or another app's, nor be extended.
for other in core $(ls "$root/backend/apps"); do
  [ "$other" = core ] || [ -f "$root/backend/apps/$other/app.json" ] || continue
  case "$slug" in "${other}_"*) echo "slug '$slug' starts with '${other}_', which '$other' owns" >&2; exit 1;; esac
  case "$other" in "${slug}_"*) echo "app '$other' already uses the '${slug}_' prefix" >&2; exit 1;; esac
done
[[ $name =~ ^[A-Za-z0-9][A-Za-z0-9\ -]{0,39}$ ]] || { echo "name: letters, digits, spaces and hyphens, up to 40" >&2; exit 1; }
backend="$root/backend/apps/$slug"
# Prefix for the scaffold's Pydantic models: FastAPI module-qualifies schemas whose class names collide.
pascal=$(printf '%s' "$slug" | awk -F_ '{for (i = 1; i <= NF; i++) $i = toupper(substr($i, 1, 1)) substr($i, 2)} 1' OFS=)
frontend="$root/frontend/src/apps/$slug"
[ ! -e "$backend" ] && [ ! -e "$frontend" ] || { echo "app '$slug' already exists" >&2; exit 1; }
# The contract test fails two apps' same-named models, so refuse a slug whose models an app already has.
if clash=$(grep -rlE "^class ${pascal}Item(In)?\(" "$root/backend/apps" --include='*.py' --exclude-dir=tests); then
  echo "slug '$slug' would define ${pascal}Item, which $(echo "$clash" | head -1 | sed "s|$root/||") already defines" >&2; exit 1
fi

# App migrations are stamped 20261101000000 or later.
stamp=$(date -u +%Y%m%d%H%M%S)
[ "$stamp" -ge 20261101000000 ] || stamp=20261101000000

mkdir -p "$backend/migrations" "$backend/docs" "$backend/tests"
touch "$backend/__init__.py" "$backend/tests/__init__.py"

cat > "$backend/app.json" <<EOF
{
  "slug": "$slug",
  "name": "$name",
  "description": "",
  "path": "/$slug",
  "icon": "grid",
  "roles": ["admin", "member"],
  "order": 500,
  "docs": "docs/index.md",
  "version": "0.1.0",
  "requires_core": ">=0.1,<1",
  "settings_cards": [],
  "sheets": [],
  "publishes": []
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

cat > "$backend/service.py" <<EOF
"""App-internal: routes call this.

Publish a function in api.py (and list it in app.json "publishes") only when another app needs it.
"""

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

cat > "$backend/models.py" <<EOF
from pydantic import BaseModel, Field

# OpenAPI names are global: prefix with the app; shared Badge/Deleted come from backend.core.responses.


class ${pascal}ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ${pascal}Item(BaseModel):
    id: int
    name: str
    owner_user_id: int
    created_at: str
    updated_at: str
EOF

cat > "$backend/router.py" <<EOF
from fastapi import APIRouter, Depends

from backend.apps.$slug import service
from backend.apps.$slug.models import ${pascal}Item, ${pascal}ItemIn
from backend.core.auth.deps import User, current_user

router = APIRouter()


@router.get("/items", response_model=list[${pascal}Item])
def list_items(user: User = Depends(current_user)) -> list[dict]:
    return service.list_items(user)


@router.post("/items", response_model=${pascal}Item)
def create_item(body: ${pascal}ItemIn, user: User = Depends(current_user)) -> dict:
    return service.create_item(user, body.name)


@router.get("/items/{item_id}", response_model=${pascal}Item)
def get_item(item_id: int, user: User = Depends(current_user)) -> dict:
    return service.get_item(user, item_id)
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
    """Demo data for PREVIEW_MODE; runs on every preview boot, so keep it idempotent."""
EOF

cat > "$backend/docs/index.md" <<EOF
---
title: $name
---
What this app is for, written for the people who use it.
EOF

# pytest collects backend/apps/*/tests; the fixtures (db, login_as, freeze, client, make_user) come from
# backend/testing/fixtures.py, so the app needs no conftest.
cat > "$backend/tests/test_$slug.py" <<EOF
def test_a_member_creates_and_reads_an_item(login_as):
    member = login_as("member")
    item = member.post("/api/$slug/items", json={"name": "First"}).json()
    assert member.get(f"/api/$slug/items/{item['id']}").json()["name"] == "First"
EOF

if [ -d "$root/frontend/src" ]; then
mkdir -p "$frontend"
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
function App() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-8 md:px-8">
      <h1 className="m-0 font-display text-2xl text-sf-ink">$name</h1>
    </div>
  );
}

export default { slug: '$slug', App } satisfies AppModule;
EOF
created_frontend=" and frontend/src/apps/$slug"
else
created_frontend=" (no frontend/src here, so no screen placeholders)"
fi

echo "Created backend/apps/$slug${created_frontend}."
echo "Then: uv run pytest   (the app contract, and backend/apps/$slug/tests)"
echo "      scripts/gen-types.sh   (commit frontend/src/core/api/types.gen.ts with the app)"
echo "      scripts/seed-labels.sh (adds the app:$slug label)"
