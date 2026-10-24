"""Smart import: vCard and CSV parsing, the model fallback (stubbed), and confirm into core's
directory with organizations resolved and a failing row skipped. Behaviour ported from
CakeCRM's smart-import suite (docs/PROVENANCE.md)."""

import pytest

from backend.apps.crm import smart_import
from backend.core import db as core_db
from backend.core.agent import llm
from backend.core.contacts import api as contacts
from backend.core.errors import Invalid

VCF = b"""BEGIN:VCARD
VERSION:3.0
FN:Zo\xc3\xab D\xc3\xa9mo
item1.EMAIL;type=INTERNET:zoe@example.com
TEL;type=CELL:555-0103
TEL;type=HOME:555-9999
ORG:Demo Caf\xc3\xa9 Group;Kitchen
TITLE:Manager
NOTE:Met at the fair
 and liked the scones
END:VCARD
BEGIN:VCARD
N:Example;Ada;;;
EMAIL:ada@example.com
END:VCARD
BEGIN:VCARD
NOTE:nobody
END:VCARD
"""


@pytest.fixture
def me(app, make_user):
    return make_user("member")


def test_vcard(me):
    out = smart_import.parse(me, "contacts.vcf", VCF)
    assert out["method"] == "vcf"
    zoe, ada = out["people"]
    assert (zoe["name"], zoe["email"], zoe["phone"], zoe["organization"], zoe["title"]) == ("Zoë Démo", "zoe@example.com", "555-0103", "Demo Café Group Kitchen", "Manager")
    assert zoe["notes"] == "Met at the fairand liked the scones", "RFC 6350 folding joins the continuation"
    assert (ada["name"], ada["source"]) == ("Ada Example", "vCard")
    assert out["warnings"] == ["1 rows had no name, email or phone and were left out"]


def test_csv_with_known_headers(me):
    data = "First Name,Last Name,E-mail,Company,Tags,\nAda,Example,ada@example.com,Example Bakery Supply,\"vip, wholesale\",stray\n,,,,\n".encode()
    out = smart_import.parse(me, "people.CSV", data)
    assert out["method"] == "csv"
    assert out["people"] == [{
        "name": "Ada Example", "email": "ada@example.com", "phone": "", "organization": "Example Bakery Supply",
        "title": "", "source": "", "notes": "", "tags": ["vip", "wholesale"],
    }], "the unnamed trailing column is never read as a field"  # fmt: skip


def test_unusual_files_go_to_the_model_outside_any_transaction(me, monkeypatch):
    def model(system, prompt, *, tier, max_tokens):
        assert not core_db.in_transaction() and tier == "light"
        assert "Who,Mail\nAda,ada@example.com" in prompt
        return '```json\n{"contacts": [{"name": "Ada Example", "email": "ada@example.com", "company": "Example Bakery Supply"}, {"notes": "x"}]}\n```'

    monkeypatch.setattr(smart_import.llm, "complete", model)
    out = smart_import.parse(me, "odd.csv", b"Who,Mail\nAda,ada@example.com\n")
    assert (out["method"], [p["organization"] for p in out["people"]]) == ("ai", ["Example Bakery Supply"])
    assert out["warnings"] == ["1 rows had no name, email or phone and were left out"]


def test_without_a_provider_an_unusual_file_is_refused_with_advice(me):
    with pytest.raises(Invalid, match="Rename the columns"):
        smart_import.parse(me, "notes.txt", b"Ada Example, ada@example.com")


@pytest.mark.parametrize("reply", ["no idea", "{}", '"just a string"'])
def test_an_unreadable_model_reply_is_refused(me, monkeypatch, reply):
    monkeypatch.setattr(smart_import.llm, "complete", lambda *a, **k: reply)
    with pytest.raises(Invalid, match="could not read"):
        smart_import.parse(me, "notes.txt", b"Ada Example")


def test_a_provider_error_is_refused(me, monkeypatch):
    def fail(*a, **k):
        raise llm.ProviderError("overloaded")

    monkeypatch.setattr(smart_import.llm, "complete", fail)
    with pytest.raises(Invalid, match="could not read this file"):
        smart_import.parse(me, "notes.txt", b"Ada Example")


def test_size_and_binary_guards(me):
    with pytest.raises(Invalid, match="2 MB"):
        smart_import.parse(me, "big.csv", b"x" * (smart_import.MAX_BYTES + 1))
    with pytest.raises(Invalid, match="Binary"):
        smart_import.parse(me, "photo.jpg", b"\xff\xd8\x00\x10")
    assert smart_import.parse(me, "empty.csv", b"  \n")["warnings"] == ["The file is empty"]


def test_confirm_creates_people_links_organizations_and_skips_a_bad_row(me):
    with core_db.transaction() as conn:
        existing = contacts.create_organization_in(conn, me, name="Example Bakery Supply")["id"]
    people = [
        {"name": "Ada Example", "email": "ada@example.com", "phone": "", "organization": "example bakery supply", "title": "Owner", "source": "", "notes": "", "tags": ["vip"]},
        {"name": "Zoë Démo", "email": "", "phone": "555-0103", "organization": "Demo Café Group", "title": "", "source": "vCard", "notes": "", "tags": []},
        {"name": "Bad Tags", "email": "", "phone": "", "organization": "", "title": "", "source": "", "notes": "", "tags": [1]},
    ]  # fmt: skip
    out = smart_import.confirm(me, people)
    assert (out["created"], out["organizations_linked"], len(out["person_ids"])) == (2, 2, 2)
    assert len(out["skipped"]) == 1 and out["skipped"][0].startswith("Row 3 (Bad Tags): ")
    ada = contacts.get_person(me, out["person_ids"][0])
    assert (ada["email"], ada["tags"], ada["owner_user_id"]) == ("ada@example.com", ["vip"], me.id)
    assert [(o["organization_id"], o["role"]) for o in ada["organizations"]] == [(existing, "Owner")], "matched case-insensitively"
    assert contacts.get_person(me, out["person_ids"][1])["organizations"][0]["name"] == "Demo Café Group"


def test_confirm_skips_people_already_in_contacts_and_repeated_rows(me):
    with core_db.transaction() as conn:
        contacts.create_person_in(conn, me, name="Known Person", email="Known@Example.com")

    def person(name, email="", organization=""):
        return {"name": name, "email": email, "phone": "", "organization": organization, "title": "", "source": "", "notes": "", "tags": []}

    out = smart_import.confirm(me, [
        person("Ada Example", "ada@example.com"), person("Known Again", " known@example.com", "Orphan Org"),
        person("Ada Twin", "ADA@example.com"), person("Known Person"), person("No Email"), person("no email"),
    ])  # fmt: skip
    assert out["created"] == 2 and out["skipped"] == [
        "Row 2 (Known Again): already in contacts (same email)", "Row 3 (Ada Twin): the same email as an earlier row",
        "Row 4 (Known Person): already in contacts (same name)", "Row 6 (no email): the same name as an earlier row",
    ]  # fmt: skip
    assert core_db.one("SELECT count(*) AS n FROM core_organizations WHERE name = 'Orphan Org'")["n"] == 0, "a skipped row creates no organization"


def test_the_routes(login_as):
    member = login_as("member")
    parsed = member.post("/api/crm/import/parse", files={"file": ("contacts.vcf", VCF, "text/vcard")})
    assert parsed.status_code == 200 and len(parsed.json()["people"]) == 2
    done = member.post("/api/crm/import/confirm", json={"people": parsed.json()["people"]})
    assert done.status_code == 200 and done.json()["created"] == 2
    again = member.post("/api/crm/import/confirm", json={"people": parsed.json()["people"]}).json()
    assert (again["created"], len(again["skipped"])) == (0, 2), "importing the same file twice adds nobody"
    assert member.post("/api/crm/import/confirm", json={"people": []}).status_code == 422
