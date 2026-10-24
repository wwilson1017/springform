"""CRM reference data and preview samples: both run again on every boot, so both are idempotent."""

from backend.apps.crm import seed, stage_criteria
from backend.core import db as core_db, preview
from backend.core.contacts import seed as contacts_seed


def run(fn):
    with core_db.transaction() as conn:
        fn(conn)


def test_seed_is_idempotent_and_keeps_an_install_s_edits(app):
    run(seed.seed)
    stage_criteria.set_criteria("lead", "Our own words", ["One"])
    run(seed.seed)
    rows = core_db.rows("SELECT stage, summary FROM crm_stage_criteria ORDER BY id")
    assert [r["stage"] for r in rows] == ["lead", "qualified", "proposal", "negotiation", "won", "lost"]
    assert rows[0]["summary"] == "Our own words"
    assert len(core_db.rows("SELECT * FROM crm_meta")) == 1


def test_sample_builds_the_pipeline_once(app, make_user):
    run(seed.sample)
    assert core_db.rows("SELECT * FROM crm_deals") == [], "nothing without an admin to act as"
    admin, member = make_user("admin"), make_user("member")
    run(seed.seed)
    run(contacts_seed.sample)  # preview seeds core's sample directory first
    run(seed.sample)
    deals = core_db.rows("SELECT title, stage, owner_user_id, person_id, organization_id, value_cents FROM crm_deals ORDER BY id")
    assert [d["stage"] for d in deals] == ["proposal", "negotiation", "qualified", "lead", "won", "lost"]
    assert {d["owner_user_id"] for d in deals} == {admin.id, member.id}
    assert all(d["person_id"] and d["organization_id"] for d in deals), "deals hang off the sample directory"
    assert all(isinstance(d["value_cents"], int) for d in deals)
    assert core_db.one("SELECT sample_data_loaded FROM crm_meta")["sample_data_loaded"] == 1
    counts = [core_db.one(f"SELECT count(*) AS n FROM {t}")["n"] for t in ("crm_deals", "crm_activity_log", "core_people")]
    run(seed.sample)
    assert [core_db.one(f"SELECT count(*) AS n FROM {t}")["n"] for t in ("crm_deals", "crm_activity_log", "core_people")] == counts
    assert all(e.endswith(".example.com") for (e,) in core_db.get_conn().execute("SELECT email FROM core_people WHERE email IS NOT NULL"))


def test_preview_seeds_the_sample_directory_before_the_deals(app, monkeypatch):
    monkeypatch.setenv("PREVIEW_MODE", "1")
    preview.seed()  # no core startup hook has run
    deals = core_db.rows("SELECT person_id, organization_id FROM crm_deals")
    assert len(deals) == len(seed.SAMPLE) and all(d["person_id"] and d["organization_id"] for d in deals)
