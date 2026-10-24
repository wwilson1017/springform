"""The reports API: role-filtered listing, params checked against the report's spec, 403/404,
and the Example report applying can_read per row."""

import pytest

from backend.core.reports import registry as reports, service
from backend.core.reports.registry import Report

PARAMS = {
    "type": "object",
    "properties": {
        "since": {"type": "string", "format": "date", "title": "Since"},
        "limit": {"type": "integer", "default": 10},
        "ratio": {"type": "number"},
        "flag": {"type": "boolean", "default": False},
        "size": {"type": "string", "enum": ["s", "m", "l"]},
    },
    "required": ["since"],
}


def _echo(params, user):
    return ["param", "value"], [(k, v) for k, v in sorted(params.items())]


@pytest.fixture
def extra_reports(app):
    """Reports beside the Example's: one with params, one admin-only, one from an admin-only app."""
    reports.register(Report(key="testing.echo", label="Echo", app="testing", run=_echo, params=PARAMS))
    reports.register(Report(key="testing.secret", label="Secret", app="testing", run=_echo, admin_only=True))
    reports.register(Report(key="adminapp.audit", label="Audit", app="adminapp", run=_echo, roles=("admin",)))


def test_list_is_filtered_by_role(extra_reports, login_as):
    admin, member = login_as("admin"), login_as("member")
    listed = member.get("/api/core/reports").json()
    assert [r["key"] for r in listed] == ["example.widgets_by_color", "testing.echo"]
    assert listed[0] == {"key": "example.widgets_by_color", "label": "Widgets by colour", "app": "example", "params": None, "admin_only": False}
    assert listed[1]["params"] == PARAMS
    assert [r["key"] for r in admin.get("/api/core/reports").json()] == [
        "example.widgets_by_color", "testing.echo", "testing.secret", "adminapp.audit",
    ]


def test_run_checks_who_may_run_it(extra_reports, login_as):
    admin, member = login_as("admin"), login_as("member")
    assert member.get("/api/core/reports/nope.nothing").status_code == 404
    assert member.get("/api/core/reports/testing.secret").json() == {"detail": "admin_only"}
    assert member.get("/api/core/reports/adminapp.audit").json() == {"detail": "forbidden"}
    assert admin.get("/api/core/reports/testing.secret").json() == {"columns": ["param", "value"], "rows": []}
    assert admin.get("/api/core/reports/adminapp.audit").status_code == 200


def test_params_are_coerced_defaulted_and_refused(extra_reports, login_as):
    member = login_as("member")
    run = lambda **q: member.get("/api/core/reports/testing.echo", params=q)  # noqa: E731

    r = run(since="2026-11-01", ratio="0.5", flag="true", size="m", limit="3")
    assert r.json() == {
        "columns": ["param", "value"],
        "rows": [["flag", True], ["limit", 3], ["ratio", 0.5], ["since", "2026-11-01"], ["size", "m"]],
    }
    assert run(since="2026-11-01", size="").json()["rows"] == [["flag", False], ["limit", 10], ["since", "2026-11-01"]]
    for bad, detail in (
        ({}, "since: required"),
        ({"since": "2026-02-30"}, "since: expected a date (YYYY-MM-DD)"),
        ({"since": "2026-11-01", "limit": "3.5"}, "limit: expected an integer"),
        ({"since": "2026-11-01", "ratio": "nan"}, "ratio: expected a number"),
        ({"since": "2026-11-01", "flag": "yes"}, "flag: expected true or false"),
        ({"since": "2026-11-01", "size": "xl"}, "size: one of s, m, l"),
        ({"since": "2026-11-01", "format": "csv"}, "unknown param: format"),
    ):
        r = run(**bad)
        assert (r.status_code, r.json()) == (422, {"detail": detail}), bad
    # Python callers (the CSV route) may pass typed values.
    rows = service.run(member.principal, "testing.echo", {"since": "2026-11-01", "limit": 4, "flag": True})["rows"]
    assert rows == [["flag", True], ["limit", 4], ["since", "2026-11-01"]]


def test_example_report_hides_private_widgets_from_another_member(login_as):
    owner, other = login_as("member"), login_as("member")
    owner.post("/api/example/widgets", json={"name": "Secret", "color": "plum", "is_private": True})
    owner.post("/api/example/widgets", json={"name": "Public", "color": "teal"})
    url = "/api/core/reports/example.widgets_by_color"
    assert owner.get(url).json() == {"columns": ["color", "widgets"], "rows": [["plum", 1], ["teal", 1]]}
    assert other.get(url).json() == {"columns": ["color", "widgets"], "rows": [["teal", 1]]}
    assert other.get(url, params={"color": "plum"}).status_code == 422  # it declares no params


@pytest.mark.parametrize(
    "spec",
    [
        {"properties": {}},  # no "type": "object"
        {"type": "object", "properties": {"a": {"type": "array"}}},
        {"type": "object", "properties": {"a": {"type": "integer", "format": "date"}}},
        {"type": "object", "properties": {"a": {"type": "string", "format": "email"}}},
        {"type": "object", "properties": {"a": {"type": "string", "minLength": 2}}},
        {"type": "object", "properties": {}, "required": ["a"]},
        [{"name": "a", "type": "string"}],
    ],
)
def test_register_refuses_params_outside_the_spec(spec):
    with pytest.raises(ValueError, match="Report 'testing.bad': params"):
        reports.register(Report(key="testing.bad", label="Bad", app="testing", run=_echo, params=spec))
    assert reports.get("testing.bad") is None
