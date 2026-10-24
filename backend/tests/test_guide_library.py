import pytest

from backend.core.guide import library

CORE_SLUGS = [
    "getting-started", "signing-in", "people-and-organizations", "apps-and-launcher", "whisk", "mcp-connector",
    "requests", "backups-and-restore", "google-sign-in-setup",
]  # fmt: skip


def _corpus(tmp_path, files: dict[str, str]):
    folder = tmp_path / "docs"
    folder.mkdir(exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    return library.load((("core", str(folder)),))


def _topic(title: str, summary: str = "", body: str = "Body.", order: int | None = None) -> str:
    front = f"title: {title}\nsummary: {summary}\n" + (f"order: {order}\n" if order is not None else "")
    return f"---\n{front}---\n{body}\n"


def test_every_installed_topic_loads_within_the_rules(app):
    """Fails a fork's CI as soon as a core or app doc breaks the front-matter rules or the cap."""
    topics = library.load(library.sources())
    assert [t.slug for t in topics if t.app == "core"] == CORE_SLUGS
    assert all(t.summary for t in topics if t.app == "core")
    assert "example" in [t.slug for t in topics]


def test_list_read_and_search_routes(login_as):
    member = login_as("member")
    listed = member.get("/api/core/guide").json()
    assert [t["slug"] for t in listed][: len(CORE_SLUGS)] == CORE_SLUGS
    assert {"slug": "example", "title": "Example app", "summary": "", "app": "example"} in listed

    topic = member.get("/api/core/guide/requests").json()
    assert topic["slug"] == "requests" and topic["app"] == "core" and "## File a request" in topic["body_markdown"]
    assert member.get("/api/core/guide/nope").status_code == 404

    hits = member.get("/api/core/guide/search", params={"q": "encryption key backup"}).json()
    assert hits[0]["slug"] == "backups-and-restore" and set(hits[0]) == {"slug", "title", "snippet", "app"}
    assert "key" in hits[0]["snippet"].lower()
    assert member.get("/api/core/guide/search", params={"q": "how do I"}).json() == []
    assert len(member.get("/api/core/guide/search", params={"q": "settings", "limit": 2}).json()) == 2


def test_hidden_app_topics_are_hidden_from_members(login_as):
    admin, member = login_as("admin"), login_as("member")
    admin.patch("/api/core/apps/example", json={"hidden": True})
    assert "example" not in [t["slug"] for t in member.get("/api/core/guide").json()]
    assert member.get("/api/core/guide/example").status_code == 404
    assert admin.get("/api/core/guide/example").status_code == 200


def test_search_ranks_title_then_summary_then_body_and_is_deterministic(tmp_path):
    corpus = _corpus(tmp_path, {
        "c-body.md": _topic("Other", body="Send an invoice to the customer."),
        "b-summary.md": _topic("Billing", summary="How each invoice is numbered"),
        "a-title.md": _topic("Invoices"),
        "d-none.md": _topic("Unrelated"),
        "e-tie.md": _topic("Billing", summary="How each invoice is numbered"),
    })  # fmt: skip
    ranked = [t.slug for t, _ in library.search(corpus, "invoice")]
    assert ranked == ["a-title", "b-summary", "e-tie", "c-body"]  # equal scores break on slug
    assert ranked == [t.slug for t, _ in library.search(corpus, "INVOICES?")]  # case and plural fold
    assert [t.slug for t, _ in library.search(corpus, "invoice billing")][0] == "b-summary"
    assert library.search(corpus, "the and of") == []
    _, snippet = library.search(corpus, "customer")[0]
    assert snippet == "Send an invoice to the customer."
    headed = _corpus(tmp_path, {"f-headed.md": _topic("Keys", body="## Customer keys\n\nAsk the customer for a key.")})
    assert library.search(headed, "customer key")[0][1] == "Ask the customer for a key."  # never a bare heading


def test_cap_and_front_matter_rules(tmp_path):
    assert len(_corpus(tmp_path, {"ok.md": _topic("Ok", body="x" * library.MAX_TOPIC_CHARS)})) == 1
    broken = {
        "long.md": _topic("Long", body="x" * (library.MAX_TOPIC_CHARS + 1)),
        "keys.md": "---\ntitle: T\ndescription: wrong key\n---\nBody\n",
        "untitled.md": "---\nsummary: no title\n---\nBody\n",
        "nofront.md": "Just text\n",
        "order.md": _topic("T", order="soon"),
        "Bad_Name.md": _topic("T"),
    }
    for name, text in broken.items():
        folder = tmp_path / name.replace(".", "_")
        folder.mkdir()
        (folder / name).write_text(text, encoding="utf-8")
        with pytest.raises(library.GuideError):
            library.load((("core", str(folder)),))


def test_app_slugs_and_order(tmp_path):
    app_docs = tmp_path / "app"
    app_docs.mkdir()
    (app_docs / "index.md").write_text(_topic("Shop", order=1), encoding="utf-8")
    (app_docs / "returns.md").write_text(_topic("Returns", order=0), encoding="utf-8")
    core = tmp_path / "core"
    core.mkdir()
    (core / "z-first.md").write_text(_topic("First", order=1), encoding="utf-8")
    (core / "a-later.md").write_text(_topic("Later"), encoding="utf-8")
    topics = library.load((("core", str(core)), ("shop", str(app_docs))))
    assert [(t.slug, t.app) for t in topics] == [
        ("z-first", "core"),
        ("a-later", "core"),
        ("shop.returns", "shop"),
        ("shop", "shop"),
    ]
    (core / "shop.md").write_text(_topic("Clash"), encoding="utf-8")
    with pytest.raises(library.GuideError, match="duplicate"):
        library.load((("core", str(core)), ("shop", str(app_docs))))


def test_runtime_skips_a_bad_topic_and_keeps_the_rest(tmp_path, monkeypatch, caplog):
    core, app_docs = tmp_path / "core", tmp_path / "app"
    core.mkdir()
    app_docs.mkdir()
    (core / "good.md").write_text(_topic("Good"), encoding="utf-8")
    (core / "shop.md").write_text(_topic("Core shop"), encoding="utf-8")
    (core / "long.md").write_text(_topic("Long", body="x" * (library.MAX_TOPIC_CHARS + 1)), encoding="utf-8")
    (core / "Bad_Name.md").write_text(_topic("Bad"), encoding="utf-8")
    (app_docs / "index.md").write_text(_topic("App shop"), encoding="utf-8")  # slug "shop": duplicate
    (app_docs / "returns.md").write_text("no front matter\n", encoding="utf-8")
    (app_docs / "help.md").write_text(_topic("Help"), encoding="utf-8")
    sources = (("core", str(core)), ("shop", str(app_docs)))

    with pytest.raises(library.GuideError):  # tests and CI stay strict
        library.load(sources)
    monkeypatch.setattr(library, "sources", lambda: sources)
    assert [(t.slug, t.title) for t in library.topics()] == [
        ("good", "Good"),
        ("shop", "Core shop"),
        ("shop.help", "Help"),
    ]
    skipped = " ".join(r.getMessage() for r in caplog.records if r.levelname == "WARNING")
    for name in ("long.md", "Bad_Name.md", "index.md", "returns.md"):
        assert name in skipped


def test_warm_never_raises(monkeypatch):
    def boom():
        raise library.GuideError("bad topic")

    monkeypatch.setattr(library, "topics", boom)
    library.warm()
