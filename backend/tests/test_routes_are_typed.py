"""Every core route declares a response model, so `types.gen.ts` describes its body. Read from the
OpenAPI schema, which is what scripts/gen-types.sh generates the types from: a route is typed when
each success body it documents names a schema (`$ref`); a 204 has no body to type.

In scope: `/api/core/*` (MCP included), `/api/agent/*` and `/api/health`. Apps are out of scope, and
so are `/api/auth/*` and `/api/me`, whose session and sign-in bodies auth keeps untyped for now.
A core route that does not declare a model is listed in UNTYPED, one line each, with the reason."""

import json

from fastapi import APIRouter, FastAPI, Response
from pydantic import BaseModel

SCOPE = ("/api/core/", "/api/agent/", "/api/health")

UNTYPED = {  # "METHOD /path": why it answers without a response model
    "POST /api/agent/chat": "a server-sent event stream, not one JSON body",
    "GET /api/core/backups/{stamp}/download": "a file download",
    "GET /api/core/files/{file_id}/download": "a file download",
    "GET /api/core/files/{file_id}/thumb": "a JPEG",
    "GET /api/core/export": "a ZIP download",
    "GET /api/core/reports/{key}/csv": "a CSV download",
    "GET /api/core/export/preview": "not typed yet: {tables: [{name, columns, estimated_rows}]}",
    "GET /api/core/fields/values": "keyed by each install's own custom field keys",
    "PUT /api/core/fields/values": "keyed by each install's own custom field keys",
    "GET /api/core/memory/facts": "not typed yet: members and admins get different keys (admins add provenance)",
    "POST /api/core/memory/facts": "not typed yet: members and admins get different keys (admins add provenance)",
    "DELETE /api/core/memory/facts/{fact_id}": "not typed yet: the admin's view of the forgotten fact",
    "GET /api/core/context-files": "not typed yet: file metadata with the caller's can_read and can_edit",
    "GET /api/core/context-files/{filename}": "not typed yet: one file with the caller's can_read and can_edit",
    "PUT /api/core/context-files/{filename}": "not typed yet: one file with the caller's can_read and can_edit",
}


def in_scope(spec: dict) -> dict[str, dict]:
    return {f"{m.upper()} {p}": op for p, ops in spec["paths"].items() if p.startswith(SCOPE) for m, op in ops.items()}


def untyped(spec: dict) -> set[str]:
    """In-scope operations with a success response whose body names no schema."""
    return {
        route
        for route, op in in_scope(spec).items()
        for code, response in op["responses"].items()
        if code.startswith("2") and code != "204" and "$ref" not in json.dumps(response.get("content", {}))
    }


def test_core_routes_declare_response_models(app):
    spec = app.openapi()
    routes = in_scope(spec)
    assert {"GET /api/health", "GET /api/core/backups", "GET /api/agent/status", "GET /api/core/mcp/links"} <= routes.keys()
    found = untyped(spec)
    assert sorted(found - UNTYPED.keys()) == [], "declare a response_model, or list the route in UNTYPED with a reason"
    assert sorted(UNTYPED.keys() - found) == [], "stale UNTYPED entries: the route is typed now, or gone"


def test_the_check_flags_an_untyped_route_and_passes_a_typed_one():
    class Thing(BaseModel):
        id: int

    router = APIRouter(prefix="/api/core/demo")

    @router.get("/typed", response_model=list[Thing])
    def typed() -> list[dict]:
        return []

    @router.get("/untyped")
    def bare() -> dict:
        return {}

    @router.delete("/thing", status_code=204)
    def delete_thing() -> Response:
        return Response(status_code=204)

    demo = FastAPI()
    demo.include_router(router)

    @demo.get("/api/demoapp/untyped")
    def app_route() -> dict:  # an app's route: out of scope
        return {}

    assert untyped(demo.openapi()) == {"GET /api/core/demo/untyped"}
