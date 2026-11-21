"""Photos and files in Whisk's chat (agent.md §5, "Uploads"): POST /api/agent/chat/upload end to end
with the FakeProvider, the caps and refusals, core_read_upload, blob holding, the extractors."""

import io
import json
import re
import sys
from datetime import timedelta

import pytest
from PIL import Image

from backend.core import clock, db as core_db, settings
from backend.core.agent import assembly, compaction, detached, history, uploads
from backend.core.agent.providers import fake
from backend.core.agent.providers.anthropic_provider import _api_content
from backend.core.agent.providers.fake import FakeProvider
from backend.core.agent.providers.openai_provider import _user_content
from backend.core.agent.spec import calling_conversation
from backend.core.backup import service as backup
from backend.core.files import jobs, service as files_service, storage

CSV = b"name,qty,color\nbolt,4,red\nnut,9,blue\nwasher,2,green\n"
FENCE = re.compile(r'<untrusted_external_content id="([0-9a-f]+)" source="upload" filename="parts.csv">.*?'
                   r'</untrusted_external_content id="\1">', re.S)  # fmt: skip


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    fake.reset()
    yield
    fake.reset()


def png(size=(4, 4), fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, fmt)
    return buf.getvalue()


def post(client, files, **body):
    return client.post(
        "/api/agent/chat/upload",
        data={"payload": json.dumps(body)},
        files=[("files", (name, data)) for name, data in files],
    )


def events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def leftovers() -> dict:
    return {
        "messages": core_db.one("SELECT count(*) AS n FROM core_agent_messages")["n"],
        "uploads": core_db.one("SELECT count(*) AS n FROM core_agent_uploads")["n"],
        "tmp": sorted(p.name for p in storage.tmp_dir().glob("*")) if storage.tmp_dir().exists() else [],
    }


def user_content(request) -> list:
    return [m for m in request["messages"] if m["role"] == "user"][-1]["content"]


def test_a_csv_and_a_photo_round_trip(login_as, model_requests):
    a = login_as("member")
    evs = events(post(a, [("parts.csv", CSV), ("shelf.png", png())], message="What's on the shelf?"))
    assert evs[-1]["type"] == "done"
    text = "".join(e["text"] for e in evs if e["type"] == "text")
    assert text == "You said: What's on the shelf? [attached: 1 photo(s), 1 file(s)]"
    title = next(e for e in evs if e["type"] == "title_update")["title"]
    assert title == "What's on the shelf?"

    parts = user_content(model_requests[-1])
    image, csv_part, photo_part, typed = parts
    assert image["type"] == "image" and image["media_type"] == "image/png" and image["data"]
    assert FENCE.search(csv_part["text"]) and "washer,2,green" in csv_part["text"]
    assert csv_part["text"].startswith("[Upload ") and "core_read_upload(id=" in csv_part["text"]
    assert 'kind="image"' in photo_part["text"] and "(photo attached)" in photo_part["text"]
    assert typed == {"type": "text", "text": "What's on the shelf?"}

    cid = evs[0]["id"]
    assert history.compaction_state(cid)["tainted"] == 1
    rows = core_db.rows("SELECT * FROM core_agent_uploads ORDER BY id")
    assert [(r["kind"], r["mime_type"], r["conversation_id"]) for r in rows] == [
        ("table", "text/csv", cid),
        ("image", "image/png", cid),
    ]
    assert all(storage.blob_path(r["sha256"]).is_file() for r in rows)
    message = a.get(f"/api/agent/conversations/{cid}").json()["messages"][0]
    assert message["text"] == "What's on the shelf?"
    assert message["files"] == [{"filename": "parts.csv", "kind": "table"}, {"filename": "shelf.png", "kind": "image"}]
    assert leftovers()["tmp"] == []

    # the next turn keeps the placeholder and the CSV text, but not the photo
    events(a.post("/api/agent/chat", json={"conversation_id": cid, "message": "and now?"}))
    sent = json.dumps(model_requests[-1]["messages"])
    assert '"type": "image"' not in sent and "(photo attached)" in sent and "washer,2,green" in sent


def test_a_files_only_message_gets_a_neutral_title_and_no_empty_text_part(login_as, model_requests):
    a = login_as("member")
    evs = events(post(a, [("parts.csv", CSV)]))
    assert next(e for e in evs if e["type"] == "title_update")["title"] == uploads.TITLE
    assert [p["type"] for p in user_content(model_requests[-1])] == ["text"]


def test_a_model_without_vision_gets_the_placeholder_only(login_as, monkeypatch):
    a = login_as("member")
    cid = events(post(a, [("shelf.png", png())], message="look"))[0]["id"]
    seeing = json.dumps(assembly.assemble_messages(FakeProvider("fake"), cid))
    monkeypatch.setattr(FakeProvider, "supports_images", property(lambda self: False))
    blind = json.dumps(assembly.assemble_messages(FakeProvider("fake"), cid))  # e.g. after a fallback
    assert '"type": "image"' in seeing and '"type": "image"' not in blind and "(photo attached)" in blind


@pytest.mark.parametrize(
    "files, status, detail",
    [
        ([("big.csv", b"a,b\n" * 40)], 413, "larger than the"),
        ([("notes.exe", b"MZ")], 400, "isn't a type"),
        ([("photo.heic", b"x")], 400, "HEIC"),
        ([("fake.png", b"just text")], 400, "is not a JPEG"),
        ([("bin.csv", b"a\x00b")], 400, "isn't a text CSV"),
        ([("x.csv", b"a")] * 6, 400, None),
    ],
)
def test_refused_uploads_leave_nothing_behind(login_as, files, status, detail):
    a = login_as("member")
    settings.set_setting("files.max_bytes", 100, None)
    r = post(a, files, message="hi")
    assert r.status_code == status, r.text
    if detail:
        assert detail in r.json()["detail"]
    assert leftovers() == {"messages": 0, "uploads": 0, "tmp": []}


def test_a_photo_over_the_photo_cap_and_a_request_over_the_total(login_as, monkeypatch):
    a = login_as("member")
    monkeypatch.setattr(uploads, "MAX_IMAGE_BYTES", 50)
    r = post(a, [("shelf.png", png((64, 64)))], message="hi")
    assert r.status_code == 413 and "larger than the" in r.json()["detail"]
    settings.set_setting("files.max_bytes", 10, None)
    monkeypatch.setattr(uploads, "ENVELOPE_BYTES", 100)
    r = post(a, [("parts.csv", CSV)], message="hi")
    assert (r.status_code, r.json()["detail"]) == (413, "upload_too_large")
    assert leftovers() == {"messages": 0, "uploads": 0, "tmp": []}


def test_a_request_without_a_length_or_files_is_refused(login_as):
    a = login_as("member")
    chunked = a.post(
        "/api/agent/chat/upload",
        content=iter([b"--b--\r\n"]),
        headers={"Content-Type": "multipart/form-data; boundary=b"},
    )
    assert (chunked.status_code, chunked.json()["detail"]) == (411, "length_required")
    assert post(a, [], message="hi").status_code == 422


def test_a_photo_needs_a_model_that_can_see(login_as, monkeypatch):
    a = login_as("member")
    monkeypatch.setattr(FakeProvider, "supports_images", property(lambda self: False))
    r = post(a, [("shelf.png", png())], message="look")
    assert r.status_code == 400 and r.json()["detail"].endswith("ask an admin for a model that can.")
    assert post(a, [("parts.csv", CSV)], message="ok").status_code == 200


def test_a_running_turn_refuses_and_discards_the_staged_files(login_as, monkeypatch):
    a = login_as("member")
    cid = events(post(a, [("parts.csv", CSV)], message="one"))[0]["id"]

    # a turn taking messages, where a text message would be queued (steering)
    class Busy:
        conversation_id, user_id, turn_id, steers = cid, a.principal.id, 99, []
        unattended = False  # a chat turn, not a check-in's

        def accepting(self) -> bool:
            return True

    busy = Busy()
    monkeypatch.setattr(detached, "_running", {busy})
    r = post(a, [("parts.csv", CSV + b"more,1,x\n")], conversation_id=cid, message="two")
    assert (r.status_code, r.json()["detail"]) == (409, "turn_running")  # attachments never steer
    assert busy.steers == []
    assert leftovers()["tmp"] == [] and leftovers()["uploads"] == 1


def test_another_users_conversation_is_not_found(login_as):
    a, b = login_as("member"), login_as("member")
    cid = events(post(a, [("parts.csv", CSV)], message="one"))[0]["id"]
    assert post(b, [("parts.csv", CSV)], conversation_id=cid, message="mine").status_code == 404
    assert leftovers()["tmp"] == [] and leftovers()["uploads"] == 1


# ── core_read_upload ──────────────────────────────────────────────────────────


def _uploaded(client, files) -> tuple[int, list[int]]:
    cid = events(post(client, files, message="here"))[0]["id"]
    return cid, [r["id"] for r in core_db.rows("SELECT id FROM core_agent_uploads WHERE conversation_id = ?", (cid,))]


def _read(user, cid, **args) -> str:
    token = calling_conversation.set(cid)
    try:
        return uploads.read(user, args)
    finally:
        calling_conversation.reset(token)


def test_read_upload_ranges(login_as, monkeypatch):
    a = login_as("member")
    cid, [uid] = _uploaded(a, [("parts.csv", CSV)])
    u = a.principal
    out = _read(u, cid, id=uid)
    assert out.startswith(f"[Upload {uid}: rows 1-4, columns A onward; end of the range.]")
    assert "\n3\tnut\t9\tblue\n" in out and 'source="upload"' in out
    assert "\n2\tbolt\t4\n3\tnut\t9\n" in _read(u, cid, id=uid, range="A2:B3")
    assert "\n1\tname\tqty\n" in _read(u, cid, id=uid, range="A:B")
    assert "\n3\tnut\t9\tblue\n" in _read(u, cid, id=uid, range="3:3")
    assert "\n3\t9\n" in _read(u, cid, id=uid, range="b3")
    monkeypatch.setattr(uploads, "READ_ROWS", 2)
    assert 'more rows follow, continue with range="3:"' in _read(u, cid, id=uid)
    assert 'continue with range="B3:C"' in _read(u, cid, id=uid, range="B1:C")
    monkeypatch.setattr(uploads, "READ_CHARS", 12)  # a row longer than a page shows its start and moves on
    cut = _read(u, cid, id=uid)
    assert "[row cut at 12 characters]" in cut and 'continue with range="2:"' in cut
    for bad in ("Z", "5:2", ":", "A1:B2:C3"):
        with pytest.raises(Exception, match="range"):
            _read(u, cid, id=uid, range=bad)


def test_read_upload_is_its_owners_in_its_conversation(login_as):
    a, b = login_as("member"), login_as("member")
    cid, [csv_id, photo_id] = _uploaded(a, [("parts.csv", CSV), ("shelf.png", png())])
    other, _ = _uploaded(a, [("parts.csv", CSV)])
    for user, conv, uid in [(b.principal, cid, csv_id), (a.principal, other, csv_id), (a.principal, cid, photo_id)]:
        with pytest.raises(Exception, match="No readable upload"):
            _read(user, conv, id=uid)
    with pytest.raises(Exception, match="No readable upload"):
        _read(a.principal, cid, id="x")


def test_read_upload_through_a_turn_stores_no_records(login_as):
    a = login_as("member")
    cid, [uid] = _uploaded(a, [("parts.csv", CSV)])
    evs = events(
        a.post("/api/agent/chat", json={"conversation_id": cid, "message": f'/tool core_read_upload {{"id": {uid}}}'})
    )
    end = next(e for e in evs if e["type"] == "tool_end")
    assert end["status"] == "done"
    run = core_db.one("SELECT records, result FROM core_agent_tool_runs WHERE tool = 'core_read_upload'")
    assert run["records"] == "[]" and "washer" in run["result"]


def test_read_upload_xlsx_sheets(login_as):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "Stock"
    wb.active.append(["sku", "qty"])
    wb.active.append(["A-1", 3])
    wb.create_sheet("Prices").append(["sku", "cents"])
    buf = io.BytesIO()
    wb.save(buf)
    a = login_as("member")
    cid, [uid] = _uploaded(a, [("stock.xlsx", buf.getvalue())])
    first = core_db.one("SELECT content FROM core_agent_messages WHERE conversation_id = ?", (cid,))["content"]
    assert "--- Sheet: Prices ---" in first and "A-1\\t3" in first
    assert "\n2\tA-1\t3\n" in _read(a.principal, cid, id=uid)
    assert "\n1\tsku\tcents\n" in _read(a.principal, cid, id=uid, sheet="Prices")
    listed = _read(a.principal, cid, id=uid, sheet="Nope")  # the file's own names come back fenced
    assert listed.startswith(f"[Upload {uid}: no sheet by that name") and '">\nStock\nPrices\n</untrusted' in listed
    assert "--- Sheets: Stock | Prices ---" in first


# ── Blobs ─────────────────────────────────────────────────────────────────────


def test_a_held_blob_survives_the_sweep_is_backed_up_and_is_released_with_its_conversation(login_as, freeze):
    a = login_as("member")
    freeze("2026-11-01T00:00:00Z")
    cid, _ = _uploaded(a, [("parts.csv", CSV)])
    sha = core_db.one("SELECT sha256 FROM core_agent_uploads")["sha256"]
    with core_db.transaction() as conn:
        files_service.release_in(conn, [sha])  # e.g. a core_files row with the same bytes went
        conn.execute("UPDATE core_file_blobs SET unreferenced_since = '2026-10-01T00:00:00Z'")  # a stale clock
    freeze("2026-11-20T00:00:00Z")
    assert jobs.sweep()["expired"] == 0 and storage.blob_path(sha).is_file()
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_file_blobs SET unreferenced_since = NULL")
        files_service.release_in(conn, [sha])
    assert core_db.one("SELECT unreferenced_since FROM core_file_blobs")["unreferenced_since"] is None

    row = backup.run("manual")
    assert sha in json.loads((core_db.data_dir() / "backups" / row["manifest"]).read_text())["blobs"]

    assert a.delete(f"/api/agent/conversations/{cid}").status_code == 200
    assert core_db.one("SELECT count(*) AS n FROM core_agent_uploads")["n"] == 0
    assert core_db.one("SELECT unreferenced_since FROM core_file_blobs")["unreferenced_since"] == clock.now_iso()
    freeze(clock.to_iso(clock.now() + timedelta(days=8)))
    for p in (core_db.data_dir() / "backups").glob("*.manifest.json"):
        p.unlink()
    assert jobs.sweep()["expired"] == 1 and not storage.blob_path(sha).exists()


# ── Extraction ────────────────────────────────────────────────────────────────


def _pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 10 50 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


def _docx(*paragraphs: str) -> bytes:
    import docx

    doc = docx.Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "cell text"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_pdf_and_docx_keep_text_only(login_as, model_requests):
    a = login_as("member")
    evs = events(post(a, [("memo.pdf", _pdf("Quarterly bolts")), ("plan.docx", _docx("Order more nuts."))]))
    assert evs[-1]["type"] == "done"
    sent = json.dumps(user_content(model_requests[-1]))
    assert "Quarterly bolts" in sent and "Order more nuts." in sent and "cell text" in sent
    assert sent.count('source=\\"upload\\"') == 2
    assert leftovers() == {"messages": 2, "uploads": 0, "tmp": []}


def test_long_text_is_cut_with_a_footer_and_empty_text_says_so(login_as, model_requests, monkeypatch):
    a = login_as("member")
    monkeypatch.setattr(uploads, "MAX_CHARS", 40)
    events(post(a, [("parts.csv", CSV * 5), ("blank.pdf", _pdf(""))], message="read"))
    sent = json.dumps(user_content(model_requests[-1]))
    assert "(truncated at 40 characters)" in sent and "(No extractable text found.)" in sent


def test_a_zip_bomb_and_a_missing_parser_are_refused(login_as, monkeypatch):
    a = login_as("member")
    monkeypatch.setattr(uploads, "MAX_UNZIPPED_BYTES", 100)
    r = post(a, [("plan.docx", _docx("x"))], message="read")
    assert r.status_code == 400 and "unpacks to more" in r.json()["detail"]
    monkeypatch.setitem(sys.modules, "pypdf", None)
    r = post(a, [("memo.pdf", _pdf("x"))], message="read")
    assert r.status_code == 400 and r.json()["detail"] == "This install can't read .pdf files."
    assert events(a.post("/api/agent/chat", json={"message": "plain chat still works"}))[-1]["type"] == "done"
    assert leftovers()["tmp"] == []


def test_compaction_renders_the_file_blocks_with_their_fences_closed(monkeypatch):
    monkeypatch.setattr(compaction, "MAX_ROW_CHARS", 400)
    block = uploads.delimiters.wrap_untrusted_upload("parts.csv", "x" * 1000)
    row = {
        "id": 1,
        "role": "user",
        "content": {"text": "see file", "files": [{"filename": "p", "kind": "table", "text": block}]},
    }
    out = compaction._render(row, {})
    nonce = re.search(r'id="([0-9a-f]+)"', block).group(1)
    assert out.startswith("USER: see file\nUSER ATTACHED: ") and out.endswith(
        f'</untrusted_external_content id="{nonce}">'
    )


def test_providers_translate_image_parts():
    parts = [{"type": "image", "media_type": "image/png", "data": "QUJD"}, {"type": "text", "text": "hi"}]
    assert _api_content(parts) == [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}},
        {"type": "text", "text": "hi"},
    ]
    assert _user_content(parts)[0] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}
    assert _api_content("plain") == _user_content("plain") == "plain"
