from backend.tests.test_app_contract import anonymous_reachable

BASE = "/api/core/contacts"


def _ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json()


def test_every_contacts_route_needs_a_session(app):
    assert len([p for p in app.openapi()["paths"] if p.startswith(BASE)]) == 16
    assert anonymous_reachable(app, "core/contacts") == []


def test_people_organizations_links_and_channels_over_http(login_as):
    member = login_as("member")
    acme = _ok(member.post(f"{BASE}/organizations", json={"name": "Acme Example", "domain": "acme.example.com"}))
    globex = _ok(member.post(f"{BASE}/organizations", json={"name": "Globex Sample"}))
    assert member.post(f"{BASE}/organizations", json={"name": "acme example"}).status_code == 409
    ada = _ok(member.post(f"{BASE}/people", json={
        "name": "Ada Example", "email": "ada@example.com", "phone": "555-0101", "tags": ["vip"], "owner_user_id": member.user["id"],
    }))  # fmt: skip
    link = {"person_id": ada["id"], "organization_id": acme["id"], "role": "Buyer"}
    _ok(member.post(f"{BASE}/links", json={**link, "started_on": "2026-01-05"}))
    _ok(member.post(f"{BASE}/links", json={"person_id": ada["id"], "organization_id": globex["id"], "role": "Advisor"}))
    patched = _ok(member.patch(f"{BASE}/links", json={
        "person_id": ada["id"], "organization_id": globex["id"], "role": "Advisor", "new_role": "Partner", "is_primary": True,
    }))
    assert (patched["role"], patched["is_primary"]) == ("Partner", True)
    work = _ok(member.post(f"{BASE}/channels", json={
        "owner_type": "person", "owner_id": ada["id"], "kind": "email", "value": "ada@work.example.com", "is_primary": True,
    }))
    address = _ok(member.post(f"{BASE}/addresses", json={"owner_type": "person", "owner_id": ada["id"], "line1": "1 Sample Street"}))
    assert address["is_primary"] is True
    _ok(member.patch(f"{BASE}/addresses/{address['id']}", json={"city": "Exampleville"}))

    detail = _ok(member.get(f"{BASE}/people/{ada['id']}"))
    assert detail["email"] == "ada@work.example.com" and detail["tags"] == ["vip"]
    assert (detail["owner_name"], acme["owner_name"]) == (member.user["name"], None)
    assert [(o["name"], o["role"], o["is_primary"], o["started_on"]) for o in detail["organizations"]] == [
        ("Globex Sample", "Partner", True, None), ("Acme Example", "Buyer", False, "2026-01-05"),
    ]
    assert [(c["kind"], c["value"], c["is_primary"]) for c in detail["channels"]] == [
        ("email", "ada@work.example.com", True), ("email", "ada@example.com", False), ("phone", "555-0101", True),
    ]
    assert [(a["line1"], a["city"]) for a in detail["addresses"]] == [("1 Sample Street", "Exampleville")]
    org = _ok(member.get(f"{BASE}/organizations/{acme['id']}"))
    assert [(p["name"], p["role"], p["is_primary"]) for p in org["people"]] == [("Ada Example", "Buyer", False)]

    assert _ok(member.delete(f"{BASE}/channels/{work['id']}")) == {"ok": True}
    assert _ok(member.get(f"{BASE}/people/{ada['id']}"))["email"] == "ada@example.com"
    assert _ok(member.request("DELETE", f"{BASE}/links", json=link)) == {"ok": True}
    assert member.request("DELETE", f"{BASE}/links", json=link).status_code == 404
    found = _ok(member.get(f"{BASE}/search", params={"q": "ada exam"}))
    assert [(h["kind"], h["id"], h["url"]) for h in found] == [("person", ada["id"], f"/people/{ada['id']}")]
    listed = _ok(member.get(f"{BASE}/people", params={"organization_id": globex["id"]}))
    assert [(p["id"], p["primary_organization_name"], p["owner_name"]) for p in listed["items"]] == [
        (ada["id"], "Globex Sample", member.user["name"]),
    ]
    assert member.patch(f"{BASE}/people/{ada['id']}", json={"nickname": "x"}).status_code == 422
    assert member.post(f"{BASE}/channels", json={"owner_type": "person", "owner_id": ada["id"], "kind": "fax", "value": "1"}).status_code == 422
    assert member.get(f"{BASE}/people/9999").status_code == 404


def test_archive_hides_from_lists_and_pages_are_bounded(login_as):
    member = login_as("member")
    ids = [
        _ok(member.post(f"{BASE}/people", json={"name": f"Person {n:02d}", "tags": ["even"] if n % 2 == 0 else []}))["id"]
        for n in range(1, 8)
    ]
    page = _ok(member.get(f"{BASE}/people", params={"page": 2, "page_size": 3}))
    assert (page["total"], page["page"], page["page_size"]) == (7, 2, 3)
    assert [p["name"] for p in page["items"]] == ["Person 04", "Person 05", "Person 06"]
    assert _ok(member.get(f"{BASE}/people", params={"tag": "EVEN"}))["total"] == 3
    assert _ok(member.get(f"{BASE}/people", params={"page_size": 10_000}))["page_size"] == 200

    archived = _ok(member.delete(f"{BASE}/people/{ids[0]}"))
    assert archived["archived_at"] is not None
    live = _ok(member.get(f"{BASE}/people"))
    assert live["total"] == 6 and ids[0] not in [p["id"] for p in live["items"]]
    assert [p["id"] for p in _ok(member.get(f"{BASE}/people", params={"archived": True}))["items"]] == [ids[0]]
    assert _ok(member.get(f"{BASE}/people/{ids[0]}"))["archived_at"] == archived["archived_at"]  # the detail still loads
    assert _ok(member.get(f"{BASE}/search", params={"q": "Person 01"})) == []
    restored = _ok(member.post(f"{BASE}/people/{ids[0]}/restore"))
    assert restored["archived_at"] is None and _ok(member.get(f"{BASE}/people"))["total"] == 7
    entries = _ok(member.get("/api/core/timeline", params={"entity_type": "core.person", "entity_id": ids[0]}))
    assert [c["field"] for e in entries for c in e["changes"]] == ["archived_at", "archived_at"]


def test_duplicates_merge_and_reading_a_merged_id(login_as):
    member = login_as("member")
    a = _ok(member.post(f"{BASE}/people", json={"name": "Ada Example", "email": "ada@example.com"}))["id"]
    b = _ok(member.post(f"{BASE}/people", json={"name": "Ada Example", "email": "ada@example.com"}))["id"]
    groups = _ok(member.get(f"{BASE}/people/duplicates"))
    assert [(g["match_on"], [r["id"] for r in g["records"]]) for g in groups] == [("email", [a, b]), ("name", [a, b])]
    merged = _ok(member.post(f"{BASE}/people/merge", json={"target_id": a, "source_id": b}))
    assert merged["id"] == a and len(merged["channels"]) == 1
    assert _ok(member.get(f"{BASE}/people/{b}")) == {"merged_into": a}  # HTTP 200
    assert member.patch(f"{BASE}/people/{b}", json={"name": "X"}).status_code == 409
    assert member.post(f"{BASE}/people/merge", json={"target_id": a, "source_id": b}).status_code == 422
    assert _ok(member.get(f"{BASE}/people/duplicates")) == []

    o1 = _ok(member.post(f"{BASE}/organizations", json={"name": "Acme Example"}))["id"]
    o2 = _ok(member.post(f"{BASE}/organizations", json={"name": "Acme Example Inc"}))["id"]
    _ok(member.post(f"{BASE}/organizations/merge", json={"target_id": o1, "source_id": o2}))
    assert _ok(member.get(f"{BASE}/organizations/{o2}")) == {"merged_into": o1}


def test_two_members_share_the_directory_but_not_private_widgets(login_as):
    alice, bob = login_as("member"), login_as("member")
    person = _ok(alice.post(f"{BASE}/people", json={"name": "Shared Person"}))
    _ok(bob.patch(f"{BASE}/people/{person['id']}", json={"title": "Buyer"}))
    assert _ok(alice.get(f"{BASE}/people/{person['id']}"))["title"] == "Buyer"
    _ok(bob.post("/api/example/widgets", json={"name": "Private gear", "is_private": True, "person_id": person["id"]}))
    _ok(bob.post("/api/example/widgets", json={"name": "Open gear", "person_id": person["id"]}))
    panel = lambda client: [w["name"] for w in _ok(client.get("/api/example/widgets", params={"person_id": person["id"]}))]  # noqa: E731
    assert panel(alice) == ["Open gear"]  # the widget's own rule, not the directory's
    assert panel(bob) == ["Private gear", "Open gear"]
