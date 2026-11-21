"""Memory writes keep secrets out, skip what is already held, refuse a lossy rewrite and say how big
memory is (issue #84)."""

import pytest

from backend.core import db as core_db
from backend.core.agent import registry as agent_registry
from backend.core.errors import Invalid
from backend.core.memory import facts, startup
from backend.core.memory.redact import blank_secrets

STRIPE = "sk_live_" + "a1B2c3D4e5F6g7H8i9J0kLmN"  # built here so no scanner reads a key in the source
CARD = "4111 1111 1111 1111"  # Luhn-valid Visa test number


def test_secrets_are_blanked_and_counted_but_lookalikes_stay():
    text, removed = blank_secrets(f"Stripe key {STRIPE}, wifi password: hunter22! and card {CARD}")
    assert text == "Stripe key [removed: key], wifi password: [removed: password] and card [removed: card number]"
    assert removed == {"key": 1, "password": 1, "card number": 1}
    key = "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"
    assert blank_secrets(f"deploy key {key} done")[0] == "deploy key [removed: key] done"
    for kept in (
        "Call +1 615 555 0100",  # a phone number
        "Order 4111 1111 1111 1112",  # fails Luhn
        "The password is in 1Password",
        "See https://example.com/p/4111111111111111",  # inside a URL
    ):
        assert blank_secrets(kept) == (kept, {})


def test_a_remembered_fact_is_blanked_and_a_held_one_is_not_saved_twice(db, make_user):
    u = make_user()
    saved = facts.remember(f"The shop card is {CARD} for supplier orders", author_user_id=u.id)
    assert saved["text"] == "The shop card is [removed: card number] for supplier orders"
    assert saved["removed"] == [{"kind": "card number", "count": 1}] and saved["duplicate"] is False
    first = facts.remember("Deliveries go out on Tuesdays.", author_user_id=u.id)
    again = facts.remember("deliveries go out on tuesdays", author_user_id=0, tags=["observed"])
    assert again["duplicate"] is True and again["id"] == first["id"] and again["size"] == "30/1,000 chars"
    assert len(facts.list_facts()) == 2


def test_a_context_file_write_is_blanked_and_reports_its_size(app, login_as):
    startup.on_startup()
    admin = login_as("admin")
    r = admin.put(
        "/api/core/context-files/suppliers.md", json={"content": f"# Suppliers\n\n- Flour API key {STRIPE}\n"}
    )
    assert r.status_code == 200 and r.json()["content"] == "# Suppliers\n\n- Flour API key [removed: key]\n"
    assert r.json()["removed"] == [{"kind": "key", "count": 1}]
    assert r.json()["memory_size"].endswith("/12,000 chars")


def test_whisks_rewrite_that_drops_entries_is_refused_unless_on_purpose(app, login_as):
    startup.on_startup()
    admin = login_as("admin")
    write = agent_registry.current().get("core_context_file_write").handler_in
    full = "# Suppliers\n\n- Flour: Mill Co\n- Eggs: Farm Co\n- Butter: Dairy Co\n- Sugar: Cane Co\n"
    with core_db.transaction() as conn:
        out = write(conn, admin.principal, {"filename": "suppliers.md", "content": full})
    assert out["removed"] == [] and out["memory_size"].endswith("/12,000 chars")

    lossy = "# Suppliers\n\n- Flour: Mill Co\n- Eggs: Farm Co\n"
    with pytest.raises(Invalid, match="drops 2 of its 4 entries"), core_db.transaction() as conn:
        write(conn, admin.principal, {"filename": "suppliers.md", "content": lossy})
    assert admin.get("/api/core/context-files/suppliers.md").json()["content"] == full
    with core_db.transaction() as conn:  # one of four is within the quarter
        write(conn, admin.principal, {"filename": "suppliers.md", "content": full.replace("- Sugar: Cane Co\n", "")})
    with core_db.transaction() as conn:
        write(conn, admin.principal, {"filename": "suppliers.md", "content": lossy, "drop_entries": True})
    assert admin.get("/api/core/context-files/suppliers.md").json()["content"] == lossy
    # an admin's own edit in the editor is never gated
    assert admin.put("/api/core/context-files/suppliers.md", json={"content": "# Suppliers\n"}).status_code == 200
