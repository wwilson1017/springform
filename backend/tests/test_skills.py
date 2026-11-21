"""Skills (agent.md "Skills"): only active ones reach the agent, the curator archives unused ones but
never pinned ones and never deletes, and the admin routes approve, edit, reject and write by hand."""

import pytest

from backend.core import db as core_db, skills
from backend.core.agent import agents, assembly
from backend.core.errors import NotFound
from backend.core.skills import tools


@pytest.fixture
def admin(make_user, app):
    agents.ensure_default()
    return make_user("admin")


def proposed(name="weekly-count", body="scen-secret-step", **kw) -> int:
    with core_db.transaction() as conn:
        return skills.create_in(conn, name, "Count the stock", body, author="agent", status="proposed", **kw)


def static_prompt(user) -> str:
    return assembly.system_prompt(agents.get(), user, query=None)[0]


def load(user, name):
    (spec,) = tools.get_tools()
    return spec.handler(user, {"name": name})


def row(skill_id) -> dict:
    return core_db.must(core_db.one("SELECT * FROM core_agent_skills WHERE id = ?", (skill_id,)))


def test_a_proposed_skill_is_invisible_until_approved(admin, make_user):
    member = make_user("member")
    sid = proposed()
    for status in ("proposed", "rejected", "archived"):
        with core_db.transaction() as conn:
            conn.execute("UPDATE core_agent_skills SET status = ? WHERE id = ?", (status, sid))
        assert skills.index_in(core_db.get_conn()) == ""
        assert "weekly-count" not in static_prompt(member) and "## Skills" not in static_prompt(member)
        with pytest.raises(NotFound) as e:
            load(member, "weekly-count")
        assert "scen-secret-step" not in e.value.detail and e.value.detail.endswith("Active skills: none.")
        assert row(sid)["use_count"] == 0
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_agent_skills SET status = 'proposed' WHERE id = ?", (sid,))
    skills.move(sid, "approve", admin)
    static = static_prompt(member)
    assert "- weekly-count: Count the stock" in static
    assert static.index("## Skills") < static.index(agents.CONFIRMATION_NOTE)  # the contracts still come last
    assert load(member, "Weekly-Count ")["body"] == "scen-secret-step"
    after = row(sid)
    assert after["use_count"] == 1 and after["last_used_at"] is not None


def test_a_load_names_only_active_skills(admin):
    skills.create("open-one", "Shown", "Body.", admin)
    proposed("hidden-one")
    with pytest.raises(NotFound) as e:
        load(admin, "nope")
    assert e.value.detail.endswith("Active skills: open-one.")


def test_the_index_lists_by_name_and_keeps_to_its_limit(admin, freeze):
    freeze("2026-11-01T09:00:00Z")
    for i in range(skills.INDEX_LIMIT + 2):
        skills.create(f"skill-{i:02d}", f"Does {i}", "Body.", admin)
    index = skills.index_in(core_db.get_conn())
    lines = [line for line in index.splitlines() if line.startswith("- ")]
    assert len(lines) == skills.INDEX_LIMIT and lines == sorted(lines)
    assert "- skill-00:" not in index
    freeze("2026-11-02T09:00:00Z")
    load(admin, "skill-00")  # a use brings a skill back into the listed set without reordering it
    assert "- skill-00:" in skills.index_in(core_db.get_conn())


def test_the_curator_archives_unused_skills_and_spares_pinned(admin, freeze):
    freeze("2026-08-01T09:00:00Z")
    stale = skills.create("stale-one", "Unused", "Body.", admin)["id"]
    pinned = skills.update(skills.create("pinned-one", "Unused but pinned", "Body.", admin)["id"], {"pinned": True})
    used = skills.create("used-one", "Used lately", "Body.", admin)["id"]
    restored = skills.create("restored-one", "Restored today", "Body.", admin)["id"]
    waiting = proposed("waiting-one")
    freeze("2026-09-01T09:00:00Z")
    load(admin, "used-one")
    skills.move(restored, "archive", admin)
    freeze("2026-10-29T09:00:00Z")  # 89 days after creation, 58 after the use
    skills.move(restored, "restore", admin)
    before = core_db.one("SELECT count(*) AS n FROM core_agent_skills")["n"]
    assert skills.curate() == 1
    status = {r["name"]: r["status"] for r in core_db.rows("SELECT name, status FROM core_agent_skills")}
    assert status == {
        "stale-one": "archived",
        "pinned-one": "active",
        "used-one": "active",
        "restored-one": "active",
        "waiting-one": "proposed",
    }
    assert core_db.one("SELECT count(*) AS n FROM core_agent_skills")["n"] == before  # archived, never deleted
    assert row(stale)["status"] == "archived" and row(pinned["id"])["pinned"] == 1
    assert {row(used)["status"], row(waiting)["status"]} == {"active", "proposed"}


def test_admin_routes(login_as):
    admin, member = login_as("admin"), login_as("member")
    for method, path in (
        ("GET", "/api/core/skills"), ("POST", "/api/core/skills"), ("PATCH", "/api/core/skills/1"),
        ("POST", "/api/core/skills/1/approve"),
    ):  # fmt: skip
        assert member.request(method, path, json={}).status_code == 403, path

    body = {"name": "weekly-count", "description": "Count the stock every Monday", "body": "1. Count."}
    made = admin.post("/api/core/skills", json=body).json()
    assert (made["status"], made["author"], made["author_name"]) == (
        "active",
        str(admin.user["id"]),
        admin.user["name"],
    )
    assert admin.post("/api/core/skills", json=body).json() == {"detail": "skill_name_taken"}
    assert admin.post("/api/core/skills", json={**body, "name": "x", "description": "d" * 61}).status_code == 422
    assert admin.post("/api/core/skills", json={**body, "name": "Bad Name"}).status_code == 422

    # an edit proposal: edited, then approved, takes the old one's place, pin and use
    admin.patch(f"/api/core/skills/{made['id']}", json={"pinned": True})
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_agent_skills SET use_count = 4 WHERE id = ?", (made["id"],))
    edit = proposed("weekly-count-v2", "1. Count twice.", revises_id=made["id"])
    r = admin.patch(f"/api/core/skills/{edit}", json={"name": "weekly-count", "body": "1. Count twice, then log."})
    assert r.status_code == 200 and r.json()["revises_name"] == "weekly-count"
    approved = admin.post(f"/api/core/skills/{edit}/approve").json()
    assert (approved["status"], approved["pinned"], approved["use_count"]) == ("active", True, 4)
    assert row(made["id"])["status"] == "archived"

    # a second proposal for a skill already replaced, and one whose skill changed meanwhile, are stale
    stale = proposed("other-v2", revises_id=made["id"])
    assert admin.post(f"/api/core/skills/{stale}/approve").json() == {"detail": "skill_revision_stale"}
    fresh = admin.post("/api/core/skills", json={**body, "name": "pricing"}).json()
    waiting = proposed("pricing-v2", revises_id=fresh["id"])
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_agent_skills SET updated_at = '2999-01-01T00:00:00Z' WHERE id = ?", (fresh["id"],))
    assert admin.post(f"/api/core/skills/{waiting}/approve").json() == {"detail": "skill_revision_stale"}

    rejected = proposed("not-this")
    assert admin.post(f"/api/core/skills/{rejected}/reject").json()["status"] == "rejected"
    assert admin.post(f"/api/core/skills/{rejected}/approve").json() == {"detail": "skill_not_proposed"}
    assert admin.patch(f"/api/core/skills/{rejected}", json={"body": "x"}).json() == {"detail": "skill_rejected"}
    assert admin.post(f"/api/core/skills/{fresh['id']}/archive").json()["status"] == "archived"
    assert admin.post(f"/api/core/skills/{fresh['id']}/restore").json()["status"] == "active"
    assert admin.post("/api/core/skills/999/approve").json() == {"detail": "skill_not_found"}
    assert admin.post(f"/api/core/skills/{fresh['id']}/delete").status_code == 422  # there is no delete

    page = admin.get("/api/core/skills", params={"status": "proposed"}).json()
    assert page["total"] == 2 and [s["name"] for s in page["skills"]] == ["other-v2", "pricing-v2"]
    assert admin.get("/api/core/skills", params={"status": "active", "limit": 1}).json()["total"] == 2


def test_a_skill_never_stores_a_secret(admin):
    made = skills.create(
        "log-in", "Sign in with password: hunter2-horse", "1. Use sk-ant-api03-" + "x" * 30 + ".", admin
    )
    assert "hunter2" not in made["description"] and "[removed: password]" in made["description"]
    assert "sk-ant" not in made["body"] and "[removed: key]" in made["body"]
