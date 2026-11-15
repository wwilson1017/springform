from dataclasses import fields
from importlib import import_module

import pytest

from backend.core.agent.registry import ToolSpecError, build_registry
from backend.core.agent.spec import ToolSpec, tool_def_sha256

SCHEMA = {"type": "object", "properties": {}}


def read(name="core_read", **kw) -> ToolSpec:
    defaults = {"description": "r", "input_schema": SCHEMA, "writes": False, "handler": lambda u, a: None}
    return ToolSpec(name=name, **{**defaults, **kw})


def write(name="core_write", **kw) -> ToolSpec:
    defaults = {"description": "w", "input_schema": SCHEMA, "writes": True,
                "handler_in": lambda c, u, a: None, "targets": lambda a: []}
    return ToolSpec(name=name, **{**defaults, **kw})


@pytest.mark.parametrize("specs, message", [
    ([read(), read()], "duplicate name"),
    ([read(name="read_things")], "must start with 'core_'"),
    ([read(name="core_bad name")], "1-64"),
    ([read(confirm_tier="routine")], "only valid on a write"),
    ([write(confirm_tier="always")], "confirm_tier must be 'routine'"),
    ([write(targets=None)], "needs handler_in and targets"),
    ([write(handler=lambda u, a: None, handler_in=None)], "needs handler_in and targets"),
    ([read(handler_in=lambda c, u, a: None)], "exactly one of handler and handler_in"),
    ([ToolSpec("core_x", "x", SCHEMA, writes=False, handler_in=lambda c, u, a: None)], "a read runs through handler"),
    ([read(input_schema={"type": "string"})], "input_schema"),
    ([ToolSpec("core_x", "x", SCHEMA, writes="yes", handler=lambda u, a: None)], "writes must be a bool"),
])
def test_invalid_specs_fail_the_build(specs, message):
    with pytest.raises(ToolSpecError, match=message):
        build_registry(specs)


def test_valid_shapes():
    reg = build_registry([
        read(),
        write(confirm_tier="routine"),
        write(name="core_send", handler_in=None, targets=None, handler=lambda u, a: None, external_effect=True),
        read(name="core_anything", always_confirm=True),
    ])
    assert reg.get("core_write").confirm_tier == "routine" and reg.get("nope") is None


def test_sources_apply_their_exclusions():
    reg = build_registry([
        read(),
        write(),
        read(name="core_careful", always_confirm=True),
        read(name="core_web", untrusted_source=True),
        read(name="core_protected", mcp_exposed=False),
        read(name="core_remote", always_confirm=True, untrusted_source=True, external_effect=True, server_id="1", server_url="https://x"),
    ])
    names = lambda specs: sorted(s.name for s in specs)  # noqa: E731
    assert names(reg.for_source("job")) == ["core_protected", "core_read"]
    assert names(reg.for_source("mcp")) == ["core_careful", "core_read", "core_web", "core_write"]
    assert len(reg.for_source("chat")) == 6
    with pytest.raises(ValueError):
        reg.for_source("email")


def test_for_user_applies_enabled():
    reg = build_registry([read(), read(name="core_admin", enabled=lambda u: u.role == "admin")])

    class Member:
        role = "member"

    assert [s.name for s in reg.for_user(Member())] == ["core_read"]


def test_tool_def_sha256_binds_what_was_shown_and_where_it_runs():
    base = read()
    digest = tool_def_sha256(base)
    assert digest == "481988952a0d1e504cd236e2bc31966dd0eb8b84bb483566f99b3fa58bb26995"
    assert digest == tool_def_sha256(read(summary=""))
    assert len({digest, tool_def_sha256(read(summary="x")), tool_def_sha256(read(summary="y"))}) == 3
    for changed in (
        read(description="other"), read(input_schema={"type": "object", "properties": {"a": {}}}),
        read(revision="0.2.0"), read(always_confirm=True), read(server_url="https://elsewhere"),
    ):
        assert tool_def_sha256(changed) != digest


@pytest.mark.parametrize("module", [
    "backend.core.contacts.tools", "backend.core.memory.tools", "backend.core.timeline.tools",
    "backend.core.reminders.tools", "backend.apps.crm.tools", "backend.apps.todos.tools",
    "backend.apps.example.tools",
])
def test_shipped_write_tools_have_user_facing_summaries(module):
    writes = [spec for spec in import_module(module).get_tools() if spec.writes]
    assert writes
    for spec in writes:
        assert spec.summary and spec.summary != spec.description
        assert len(spec.summary.split()) <= 12
        assert "summary" not in spec.provider_def()


def test_toolspec_fields_only_grow_at_the_end():
    # fork apps may build ToolSpec positionally, so a new field goes last
    assert [f.name for f in fields(ToolSpec)] == [
        "name", "description", "input_schema", "writes", "handler", "handler_in", "targets", "confirm_tier",
        "always_confirm", "hides_when", "enabled", "untrusted_source", "external_effect", "mcp_exposed", "app",
        "revision", "server_id", "server_url", "summary",
    ]
