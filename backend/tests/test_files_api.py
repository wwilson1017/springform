"""Files over HTTP and through the published API, on the Example app's widgets."""

import hashlib
import io

import pytest
from PIL import Image

from backend.core import db as core_db, entities, scheduler, settings
from backend.core.errors import NotFound
from backend.core.files import api as files_api, storage

W = "example.widget"


def _widget(client, **body) -> int:
    r = client.post("/api/example/widgets", json={"name": "Gear", **body})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _upload(client, entity_id: int, name: str, data: bytes, mime: str | None = None, entity_type: str = W):
    file = (name, data, mime) if mime else (name, data)
    return client.post("/api/core/files", data={"entity_type": entity_type, "entity_id": str(entity_id)}, files={"file": file})


def _png(size=(40, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, (200, 30, 30, 128)).save(buf, "PNG")
    return buf.getvalue()


def _blob_count() -> int:
    return core_db.one("SELECT count(*) AS n FROM core_file_blobs")["n"]


def test_upload_round_trips_sha256_and_dedupes(login_as):
    member = login_as("member")
    w1, w2 = _widget(member), _widget(member)
    data = b"hello world\n"
    sha = hashlib.sha256(data).hexdigest()

    first = _upload(member, w1, "notes.txt", data, "text/plain")
    assert first.status_code == 201, first.text
    f = first.json()
    assert f == {
        "id": f["id"], "filename": "notes.txt", "mime_type": "text/plain", "byte_size": len(data), "sha256": sha,
        "created_at": f["created_at"], "uploaded_by": {"id": member.user["id"], "name": member.user["name"]}, "has_thumb": False,
    }
    again = _upload(member, w1, "renamed.txt", data, "text/plain")
    assert again.status_code == 200 and again.json() == f  # same bytes on the same record: the existing row
    other = _upload(member, w2, "copy.txt", data, "text/plain")
    assert other.status_code == 201 and other.json()["id"] != f["id"] and other.json()["sha256"] == sha

    assert _blob_count() == 1
    assert storage.blob_path(sha).read_bytes() == data
    assert list(storage.tmp_dir().iterdir()) == []
    assert member.get("/api/core/files", params={"entity_type": W, "entity_id": w1}).json() == [f]
    assert member.get(f"/api/core/files/{f['id']}/download").content == data


def test_download_is_an_allow_listed_attachment_with_nosniff(login_as):
    member = login_as("member")
    w = _widget(member)
    png = _upload(member, w, "photo.png", _png(), "image/png").json()
    r = member.get(f"/api/core/files/{png['id']}/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.headers["content-disposition"] == "attachment; filename*=UTF-8''photo.png"
    assert r.headers["x-content-type-options"] == "nosniff"

    html = _upload(member, w, "résumé.html", b"<script>alert(1)</script>", "text/html").json()
    assert html["mime_type"] == "application/octet-stream"
    r = member.get(f"/api/core/files/{html['id']}/download")
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"] == "attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.html"
    assert r.headers["x-content-type-options"] == "nosniff"

    assert _upload(member, w, "x.svg", b"<svg/>", "image/svg+xml").json()["mime_type"] == "application/octet-stream"
    assert _upload(member, w, "x.xml", b"<a/>", "application/xml").json()["mime_type"] == "application/octet-stream"
    guessed = _upload(member, w, "../../etc/data.csv", b"a,b\n", "application/octet-stream").json()
    assert (guessed["filename"], guessed["mime_type"]) == ("data.csv", "text/csv")


def test_thumbnail_for_a_png_and_none_for_a_pdf(login_as):
    member = login_as("member")
    w = _widget(member)
    png = _upload(member, w, "wide.png", _png((1000, 500)), "image/png").json()
    assert png["has_thumb"] is True
    r = member.get(f"/api/core/files/{png['id']}/thumb")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    thumb = Image.open(io.BytesIO(r.content))
    assert (thumb.format, thumb.size) == ("JPEG", (320, 160))

    pdf = _upload(member, w, "doc.pdf", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\n", "application/pdf").json()
    assert pdf["has_thumb"] is False and pdf["mime_type"] == "application/pdf"
    assert member.get(f"/api/core/files/{pdf['id']}/thumb").status_code == 404


def test_another_member_is_refused_by_the_parent_records_rules(login_as):
    admin, owner, other = login_as("admin"), login_as("member"), login_as("member")
    private = _widget(owner, is_private=True)
    public = _widget(owner)
    secret = _upload(owner, private, "secret.png", _png(), "image/png").json()
    shared = _upload(owner, public, "shared.txt", b"shared", "text/plain").json()

    # Private widget: the other member cannot tell the file exists.
    assert other.get("/api/core/files", params={"entity_type": W, "entity_id": private}).status_code == 404
    for path in (f"/api/core/files/{secret['id']}/download", f"/api/core/files/{secret['id']}/thumb"):
        assert other.get(path).status_code == 404
    assert other.delete(f"/api/core/files/{secret['id']}").status_code == 404
    assert _upload(other, private, "x.txt", b"x").status_code == 404
    with pytest.raises(NotFound):
        files_api.read_bytes(other.principal, secret["id"])

    # Public widget: readable, but only its owner or an admin writes.
    assert other.get("/api/core/files", params={"entity_type": W, "entity_id": public}).json() == [shared]
    assert other.get(f"/api/core/files/{shared['id']}/download").content == b"shared"
    assert other.delete(f"/api/core/files/{shared['id']}").status_code == 403
    assert _upload(other, public, "x.txt", b"x").status_code == 403
    assert admin.delete(f"/api/core/files/{shared['id']}").status_code == 204
    assert owner.get("/api/core/files", params={"entity_type": W, "entity_id": public}).json() == []
    assert owner.get(f"/api/core/files/{shared['id']}/download").status_code == 404

    assert _upload(owner, private, "x.txt", b"x", entity_type="nope.thing").status_code == 404
    assert owner.post("/api/core/files", data={"entity_type": W}, files={"file": ("x.txt", b"x")}).status_code == 422


def test_upload_over_the_cap_is_413_and_leaves_nothing_behind(login_as):
    member = login_as("member")
    w = _widget(member)
    settings.set_setting("files.max_bytes", 10, None)
    r = _upload(member, w, "big.bin", b"x" * 11)
    assert (r.status_code, r.json()) == (413, {"detail": "file_too_large"})
    assert list(storage.tmp_dir().iterdir()) == [] and _blob_count() == 0
    assert _upload(member, w, "fits.bin", b"x" * 10).status_code == 201


def test_deleting_a_record_removes_its_files_and_releases_only_unshared_blobs(login_as):
    member = login_as("member")
    a, b = _widget(member), _widget(member)
    shared = files_api.attach(member.principal, W, a, "shared.txt", b"shared")
    files_api.attach(member.principal, W, b, "shared.txt", b"shared")
    only_a = files_api.attach(member.principal, W, a, "mine.txt", b"mine")
    with core_db.transaction() as conn:
        entities.delete_record_in(conn, W, a)
    assert core_db.rows("SELECT entity_id FROM core_files") == [{"entity_id": b}]
    since = {r["sha256"]: r["unreferenced_since"] for r in core_db.rows("SELECT * FROM core_file_blobs")}
    assert since[shared["sha256"]] is None and since[only_a["sha256"]] is not None


def test_merge_moves_files_and_the_targets_copy_wins_a_collision(login_as):
    member = login_as("member")
    target, source = _widget(member), _widget(member)
    kept = files_api.attach(member.principal, W, target, "x.txt", b"x")
    files_api.attach(member.principal, W, source, "x-dup.txt", b"x")
    moved = files_api.attach(member.principal, W, source, "y.txt", b"y")
    with core_db.transaction() as conn:
        entities.on_entity_merged_in(conn, W, target, source)
    assert sorted(f["id"] for f in files_api.list_for(member.principal, W, target)) == sorted([kept["id"], moved["id"]])
    assert files_api.list_for(member.principal, W, source) == []
    assert core_db.one("SELECT unreferenced_since FROM core_file_blobs WHERE sha256 = ?", (kept["sha256"],)) == {"unreferenced_since": None}


def test_published_api_has_in_forms(login_as):
    member = login_as("member")
    w, other = _widget(member), _widget(member)
    f = files_api.attach(member.principal, W, w, "a.txt", b"abc", "text/plain")
    assert files_api.list_for(member.principal, W, w) == [f]
    assert files_api.read_bytes(member.principal, f["id"]) == b"abc"
    with core_db.transaction() as conn:
        g = files_api.attach_in(conn, member.principal, W, w, "b.bin", b"\x00\x01")
        assert files_api.read_bytes_in(conn, member.principal, g["id"]) == b"\x00\x01"
        assert [x["id"] for x in files_api.list_for_in(conn, member.principal, W, w)] == [g["id"], f["id"]]
        files_api.delete_in(conn, member.principal, f["id"])
    files_api.delete(member.principal, g["id"])
    assert files_api.list_for(member.principal, W, w) == []
    h = files_api.attach(member.principal, W, other, "c.txt", b"c")
    files_api.move_to(W, other, w)
    assert files_api.list_for(member.principal, W, w) == [h]


def test_sweep_job_is_registered(app):
    assert scheduler.jobs()["core.files_sweep"].at == "03:30"
