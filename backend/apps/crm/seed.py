"""Reference data on every boot (stage criteria, the meta row) and PREVIEW_MODE sample deals
over core's sample directory. Both are idempotent."""

from backend.apps.crm import activity, deals, stage_criteria
from backend.core import clock
from backend.core.auth.deps import User
from backend.core.contacts import seed as contacts_seed

# Every real table the app owns, in creation order (reset deletes in reverse).
RESET_TABLES = [
    "crm_deals", "crm_person_scores", "crm_activity_log", "crm_deal_stage_events", "crm_deal_ai_touch_evidence",
    "crm_stage_criteria", "crm_field_provenance", "crm_meta",
]  # fmt: skip
EXPORT = {
    "crm_deals": {
        "entity": "crm.deal",
        "columns": [
            "id", "title", "person_id", "organization_id", "owner_user_id", "stage", "value_cents", "currency",
            "probability", "expected_close", "closed_on", "lost_reason", "deal_temperature", "notes", "lead_score",
            "ai_touch_count", "archived_at", "archived_reason", "created_at", "updated_at",
        ],
    },
}  # fmt: skip

# (title, organization, person email, stage, value in cents, temperature, owner role, extra)
SAMPLE = [
    ("Spring wholesale order", "Example Bakery Supply", "ada@bakery.example.com", "proposal", 480_000, "hot", "admin", {}),
    ("Café pastry subscription", "Demo Café Group", "zoe@cafe.example.com", "negotiation", 1_250_000, "warm", "member", {}),
    ("Holiday catering", "Fictional Events Ltd", "marie@events.example.com", "qualified", 320_000, None, "member", {}),
    ("Grocery shelf placement", "Placeholder Grocers", "linus@grocers.example.com", "lead", 900_000, "cold", "admin", {}),
    ("Dairy supply contract", "Sample Dairy Co-op", "grace@dairy.example.com", "won", 675_050, None, "admin", {}),
    ("Summer festival booth", "Fictional Events Ltd", "marie@events.example.com", "lost", 150_000, None, "member", {}),
]  # fmt: skip


def seed(conn) -> None:
    stage_criteria.seed_in(conn)
    conn.execute("INSERT OR IGNORE INTO crm_meta (id, updated_at) VALUES (1, ?)", (clock.now_iso(),))


def sample(conn) -> None:
    """Six deals across the pipeline over the sample directory, owned by the preview admin and
    member, with a little activity. Skips once any deal exists."""
    if conn.execute("SELECT 1 FROM crm_deals LIMIT 1").fetchone():
        return
    users = {r["role"]: User.from_row(dict(r)) for r in conn.execute(
        "SELECT * FROM core_users WHERE role IN ('admin', 'member') AND is_active = 1 ORDER BY id DESC"
    )}  # fmt: skip
    if "admin" not in users:
        return
    contacts_seed.sample(conn)  # core's sample directory; it skips when contacts exist
    org_ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM core_organizations")}
    person_ids = {r["email"]: r["id"] for r in conn.execute("SELECT id, email FROM core_people ORDER BY id DESC")}
    for title, org, email, stage, cents, temperature, role, extra in SAMPLE:
        owner = users.get(role, users["admin"])
        deal = deals.create_in(conn, owner, {
            "title": title, "organization_id": org_ids.get(org), "person_id": person_ids.get(email),
            "value_cents": cents, "deal_temperature": temperature, "owner_user_id": owner.id, **extra,
        })  # fmt: skip
        if stage == "lost":
            deals.mark_lost_in(conn, owner, deal["id"], "Budget moved to next year")
        elif stage != "lead":
            deals.update_in(conn, owner, deal["id"], {"stage": stage})
        if stage in ("proposal", "negotiation"):
            activity.log_in(conn, owner, "call", f"Talked through {title.lower()}", deal_id=deal["id"], person_id=person_ids.get(email))
    conn.execute("UPDATE crm_meta SET sample_data_loaded = 1, updated_at = ? WHERE id = 1", (clock.now_iso(),))
