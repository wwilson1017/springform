import pytest

from backend.core import db as core_db, memory, settings
from backend.core.agent import registry as agent_registry
from backend.core.auth.deps import system_user
from backend.core.errors import Forbidden
from backend.core.memory import context_files, facts, startup


def names(specs) -> set[str]:
    return {s.name for s in specs}


def test_routes_list_read_and_refuse_protected_writes(app, login_as):
    startup.on_startup()
    admin, member = login_as("admin"), login_as("member")

    listed = member.get("/api/core/context-files").json()
    assert [f["filename"] for f in listed] == ["soul.md", "MEMORY.md", "business.md"]
    assert [(f["is_protected"], f["can_read"], f["can_edit"]) for f in listed] == [
        (True, False, False), (True, False, False), (False, True, False),
    ]  # fmt: skip
    assert [f["can_edit"] for f in admin.get("/api/core/context-files?agent=whisk").json()] == [False, False, True]

    assert member.get("/api/core/context-files/soul.md").status_code == 403
    assert "business assistant" in admin.get("/api/core/context-files/soul.md").json()["content"]
    assert member.get("/api/core/context-files/business.md").json()["content"].startswith("# Business profile")

    r = admin.put("/api/core/context-files/business.md", json={"content": "# Business profile\n\n- Name: Test Bakery\n"})
    assert r.status_code == 200 and r.json()["updated_by"] == admin.user["id"]
    assert member.put("/api/core/context-files/business.md", json={"content": "x"}).status_code == 403
    for name in ("soul.md", "SOUL.MD", "memory.md"):
        r = admin.put(f"/api/core/context-files/{name}", json={"content": "New rules"})
        assert (r.status_code, r.json()) == (403, {"detail": "protected_file"})
    assert admin.put("/api/core/context-files/suppliers.md", json={"content": "# Suppliers"}).status_code == 200
    assert admin.put("/api/core/context-files/notes.txt", json={"content": "x"}).status_code == 422
    assert admin.put("/api/core/context-files/x.md?agent=Bad Agent", json={"content": "x"}).status_code == 422
    assert admin.get("/api/core/context-files/missing.md").status_code == 404

    startup.on_startup()  # seeding again never overwrites an edit
    assert "Test Bakery" in member.get("/api/core/context-files/business.md").json()["content"]
    assert "New rules" not in admin.get("/api/core/context-files/soul.md").json()["content"]


def test_protected_files_change_only_through_the_confirmed_admin_tool(app, login_as):
    startup.on_startup()
    admin, member = login_as("admin"), login_as("member")
    reg = agent_registry.current()
    write = reg.get("core_context_file_write")
    assert write.writes and write.always_confirm and not write.mcp_exposed and write.targets({}) == []

    assert "core_context_file_write" in names(reg.for_user(admin.principal))
    assert "core_context_file_write" not in names(reg.for_user(member.principal))
    assert names(reg.for_source("mcp")) >= {"core_memory_search", "core_memory_remember", "core_context_file_read"}
    assert "core_context_file_write" not in names(reg.for_source("mcp"))
    assert not {s.name for s in reg.for_source("job") if s.writes}  # every write tool is out
    assert names(reg.for_source("job")) >= {"core_memory_search", "core_context_file_read"}

    with core_db.transaction() as conn:  # what the engine's approval step runs
        out = write.handler_in(conn, admin.principal, {"filename": "soul.md", "content": "# Whisk\n\nBe brief."})
    assert out["is_protected"] is True
    assert admin.get("/api/core/context-files/soul.md").json()["content"] == "# Whisk\n\nBe brief."
    for who in (member.principal, system_user()):  # the service refuses even if a tool were reached
        with pytest.raises(Forbidden), core_db.transaction() as conn:
            write.handler_in(conn, who, {"filename": "soul.md", "content": "x"})


def test_memory_tools_remember_search_and_read(app, login_as):
    startup.on_startup()
    admin, member = login_as("admin"), login_as("member")
    reg = agent_registry.current()
    remember = reg.get("core_memory_remember")
    assert remember.writes and remember.confirm_tier is None and remember.targets({"text": "x"}) == []

    with core_db.transaction() as conn:
        saved = remember.handler_in(conn, member.principal, {"text": "Deliveries go out on Tuesdays", "tags": ["delivery"]})
    assert facts.get(saved["id"])["author_user_id"] == member.user["id"]

    search = reg.get("core_memory_search").handler
    assert search(member.principal, {"query": "when do deliveries go out"})["facts"][0]["text"] == "Deliveries go out on Tuesdays"
    assert search(member.principal, {"query": "business profile"})["context_files"][0]["filename"] == "business.md"
    assert search(member.principal, {"query": "assistant install"})["context_files"] == []  # soul.md is admin-only
    assert search(admin.principal, {"query": "assistant install"})["context_files"][0]["filename"] == "soul.md"

    read = reg.get("core_context_file_read").handler
    assert read(member.principal, {"filename": "business.md"})["content"].startswith("# Business profile")
    with pytest.raises(Forbidden):
        read(member.principal, {"filename": "soul.md"})


def test_context_for_orders_protected_files_first_and_respects_the_budget(db, make_user):
    admin = make_user("admin")
    with core_db.transaction() as conn:
        context_files.seed_defaults_in(conn)
        context_files.write_in(conn, "whisk", "MEMORY.md", "Standing note: quote in dollars.", admin, allow_protected=True)
        context_files.write_in(conn, "whisk", "a-first.md", "Alphabetically first, still after the protected files.", admin)
    facts.remember("Wholesale price is 30 dollars per cake", author_user_id=admin.id)
    conn = core_db.get_conn()

    block = memory.context_for(conn, admin, "whisk", "what is our wholesale price?")
    order = ["## soul.md", "## MEMORY.md", memory.FACTS_HEADER, "- Wholesale price is 30 dollars per cake",
             "## a-first.md", "## business.md"]  # fmt: skip
    assert [block.index(s) for s in order] == sorted(block.index(s) for s in order)
    assert memory.FACTS_HEADER not in memory.context_for(conn, admin, "whisk", "")
    instructions = memory.instructions_for(conn, "whisk")
    assert instructions.startswith("## soul.md") and "## MEMORY.md" in instructions and "business.md" not in instructions
    data = memory.context_for(conn, admin, "whisk", "wholesale price", include_protected=False)
    assert data.startswith(memory.FACTS_HEADER) and "## soul.md" not in data and "## business.md" in data

    settings.set_setting(memory.BUDGET_SETTING, 400, admin.id)
    small = memory.context_for(conn, admin, "whisk", "wholesale price")
    assert len(small) <= 400 and small.startswith("## soul.md") and small.endswith("…(truncated)")
    assert "## business.md" not in small
    assert memory.context_for(conn, admin, "nobody", "wholesale") == memory.FACTS_HEADER + (
        "\n\n- Wholesale price is 30 dollars per cake"
    )
    facts.forget(1, admin.id)
    assert memory.context_for(conn, admin, "nobody", "wholesale") == ""


def test_after_turn_marks_the_conversation_inside_or_outside_a_transaction(db):
    memory.after_turn(core_db.get_conn(), 7)
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_agent_observations SET pending = 0")
        memory.after_turn(conn, 7)
        memory.after_turn(conn, 8)
    rows = core_db.rows("SELECT conversation_id, pending FROM core_agent_observations ORDER BY conversation_id")
    assert rows == [{"conversation_id": 7, "pending": 1}, {"conversation_id": 8, "pending": 1}]
