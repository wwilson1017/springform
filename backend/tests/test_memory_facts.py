from backend.core.memory import facts
from backend.tests.conftest import make_client

MEMBER_KEYS = {"id", "text", "tags", "valid_from", "invalid_from"}


def test_search_ranks_by_keywords_and_folds_case_and_accents(db, make_user):
    u = make_user()
    price = facts.remember("Wholesale cheesecake price is 30 dollars per cake", author_user_id=u.id, tags=["pricing"])
    supplier = facts.remember("Cheesecake orders from the dairy go out on Mondays", author_user_id=u.id)
    facts.remember("The bakery opens at 7 on weekdays", author_user_id=u.id)
    facts.remember("Café counter closes at 3", author_user_id=u.id)

    hits = facts.search("what is the cheesecake price?")
    assert [f["id"] for f in hits] == [price["id"], supplier["id"]]  # both keywords beat one
    assert facts.search("pricing")[0]["id"] == price["id"]  # tags are indexed
    assert facts.search("CHEESE")  # case-folded prefix match
    assert facts.search("cafe")[0]["text"].startswith("Café")
    assert facts.search("") == [] and facts.search('"*)(') == []
    assert set(hits[0]) >= MEMBER_KEYS | {"author_user_id", "source_conversation_id", "created_at"}


def test_validity_window_and_soft_forget(db, make_user, freeze):
    u = make_user()
    freeze("2026-11-02T09:00:00Z")
    old = facts.remember("Delivery fee is 5 dollars", author_user_id=u.id)
    new = facts.remember("Delivery fee is 7 dollars", author_user_id=u.id)
    later = facts.remember("Delivery fee is 9 dollars", author_user_id=u.id, valid_from="2027-01-01")
    assert later["valid_from"] == "2027-01-01T00:00:00Z"

    freeze("2026-11-03T09:00:00Z")
    gone = facts.forget(old["id"], u.id)
    assert gone["invalid_from"] == "2026-11-03T09:00:00Z" and gone["invalidated_by"] == u.id
    assert facts.forget(old["id"], u.id)["invalid_from"] == "2026-11-03T09:00:00Z"  # idempotent
    assert [f["id"] for f in facts.search("delivery fee")] == [new["id"]]
    assert [f["id"] for f in facts.list_facts()] == [new["id"]]
    history = facts.search("delivery fee", include_history=True)
    assert history[0]["id"] == new["id"] and {f["id"] for f in history[1:]} == {old["id"], later["id"]}

    freeze("2027-01-02T00:00:00Z")  # the dated fact becomes current on its own
    assert {f["id"] for f in facts.list_facts()} == {new["id"], later["id"]}


def test_routes_show_provenance_to_admins_only(app, login_as):
    admin, member = login_as("admin"), login_as("member")
    r = member.post("/api/core/memory/facts", json={"text": "We close  on\npublic holidays", "tags": ["hours"]})
    assert r.status_code == 200 and set(r.json()) == MEMBER_KEYS
    fact = r.json()
    assert fact["text"] == "We close on public holidays"

    assert member.get("/api/core/memory/facts", params={"q": "holidays"}).json() == [fact]
    seen = admin.get("/api/core/memory/facts", params={"q": "holidays"}).json()[0]
    assert seen["author_user_id"] == member.user["id"] and seen["author_name"] == member.user["name"]
    assert seen["source_conversation_id"] is None and seen["created_at"]

    assert member.delete(f"/api/core/memory/facts/{fact['id']}").status_code == 403
    gone = admin.delete(f"/api/core/memory/facts/{fact['id']}")
    assert gone.status_code == 200 and gone.json()["invalidated_by"] == admin.user["id"]
    assert member.get("/api/core/memory/facts").json() == []
    assert member.get("/api/core/memory/facts", params={"history": True}).json() == []  # history is admin-only
    assert [f["id"] for f in admin.get("/api/core/memory/facts", params={"history": True}).json()] == [fact["id"]]

    assert admin.delete("/api/core/memory/facts/9999").status_code == 404
    assert member.post("/api/core/memory/facts", json={"text": "  "}).status_code == 422
    assert make_client(app).get("/api/core/memory/facts").status_code == 401
