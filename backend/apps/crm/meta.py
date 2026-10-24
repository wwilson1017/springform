"""First-run state (crm_meta) and the CRM's own reset entry point."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.apps.crm import seed
from backend.core import clock, db, registry

if TYPE_CHECKING:
    from backend.core.auth.deps import User


def get() -> dict:
    conn = db.get_conn()
    row = conn.execute("SELECT sample_data_loaded, onboarding_dismissed FROM crm_meta WHERE id = 1").fetchone()
    empty = not conn.execute(
        """SELECT 1 FROM crm_deals UNION ALL SELECT 1 FROM crm_activity_log UNION ALL SELECT 1 FROM core_people
           UNION ALL SELECT 1 FROM core_organizations LIMIT 1"""
    ).fetchone()
    return {"empty": empty, "sample_data_loaded": bool(row and row[0]), "onboarding_dismissed": bool(row and row[1])}


def dismiss_onboarding() -> dict:
    with db.transaction() as conn:
        seed.seed_meta_in(conn)
        conn.execute("UPDATE crm_meta SET onboarding_dismissed = 1, updated_at = ? WHERE id = 1", (clock.now_iso(),))
    return get()


def reset(user: User) -> dict:
    """Empty the CRM (admin): every deal through entities.delete_record_in, so its timeline,
    files, fields, reminders and change-log rows go too; then the CRM's other tables; then the
    reference data again. Never touches sqlite_sequence: ids keep climbing."""
    with db.transaction() as conn:
        counts = {
            "deals": conn.execute("SELECT count(*) FROM crm_deals").fetchone()[0],
            "activity": conn.execute("SELECT count(*) FROM crm_activity_log").fetchone()[0],
        }
        registry.reset_app_in(conn, "crm")
        seed.seed(conn)
    return counts
