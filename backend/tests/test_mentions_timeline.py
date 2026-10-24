from backend.core import db as core_db

W = "example.widget"


def _widget(client, **body) -> dict:
    r = client.post("/api/example/widgets", json={"name": "Gear", **body})
    assert r.status_code == 200, r.text
    return r.json()


def _note(client, widget_id: int, body: str) -> dict:
    r = client.post("/api/core/timeline", json={"entity_type": W, "entity_id": widget_id, "body": body})
    assert r.status_code == 200, r.text
    return r.json()


def _mention(client) -> str:
    return f"@[{client.user['name']}](user:{client.user['id']})"


def test_mentions_notify_readers_except_the_author(login_as, make_user):
    author, reader = login_as("member"), login_as("member")
    gone = make_user("member")
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_users SET is_active = 0 WHERE id = ?", (gone.id,))
    w = _widget(author)
    body = f"{_mention(reader)} can you check? cc {_mention(author)} @[Gone](user:{gone.id}) @[System](user:0) @[Nobody](user:9999)"
    entry = _note(author, w["id"], body)
    assert entry["body"] == body
    mentions = core_db.rows("SELECT user_id, display_name FROM core_timeline_mentions WHERE timeline_id = ? ORDER BY id", (entry["id"],))
    assert mentions == [
        {"user_id": reader.user["id"], "display_name": reader.user["name"]},
        {"user_id": author.user["id"], "display_name": author.user["name"]},
    ]
    listed = reader.get("/api/core/notifications").json()
    assert [(n["title"], n["message"], n["entity_type"], n["entity_id"], n["link"]) for n in listed] == [(
        f"{author.user['name']} mentioned you on Widget — Gear",
        f"@{reader.user['name']} can you check? cc @{author.user['name']} @Gone @System @Nobody",
        W, w["id"], f"/example/widgets/{w['id']}",
    )]  # fmt: skip
    assert core_db.rows("SELECT user_id FROM core_notifications") == [{"user_id": reader.user["id"]}]


def test_mention_on_a_private_record_notifies_nobody_who_cannot_read_it(login_as):
    owner, other = login_as("member"), login_as("member")
    w = _widget(owner, is_private=True)
    entry = _note(owner, w["id"], f"heads up {_mention(other)}")
    assert core_db.rows("SELECT * FROM core_timeline_mentions WHERE timeline_id = ?", (entry["id"],)) == []
    assert core_db.rows("SELECT * FROM core_notifications") == []
    assert other.get("/api/core/notifications").json() == []


def test_mentionable_lists_active_humans_only(login_as, make_user):
    member = login_as("member")
    ann = make_user("member", email="ann@example.com")
    gone = make_user("member")
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_users SET is_active = 0 WHERE id = ?", (gone.id,))
    everyone = member.get("/api/core/timeline/mentionable").json()
    ids = {u["id"] for u in everyone}
    assert member.user["id"] in ids and ann.id in ids and gone.id not in ids and 0 not in ids
    assert all(set(u) == {"id", "name"} for u in everyone)
    assert member.get("/api/core/timeline/mentionable", params={"q": "ann@"}).json() == [{"id": ann.id, "name": ann.name}]
    assert member.get("/api/core/timeline/mentionable", params={"q": "%"}).json() == []
