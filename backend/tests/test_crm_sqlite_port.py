"""The PG→SQLite checklist (docs/agents/database-and-transactions.md §11), grep-enforced on every
CRM backend module and migration: Postgres idioms that would fail or silently misbehave on SQLite
must not survive the port."""

import re
from pathlib import Path

import pytest

CRM = Path(__file__).resolve().parents[1] / "apps" / "crm"

# (name, pattern): each is a Postgres idiom with a stated SQLite replacement in the checklist.
CHECKLIST = [
    ("row locks", r"\bFOR\s+UPDATE\b|\bSKIP\s+LOCKED\b|pg_advisory"),
    ("TRUNCATE (use registry.reset_app_in)", r"\bTRUNCATE\b|RESTART\s+IDENTITY"),
    # The SQLite clock idioms are refused repo-wide by test_db.test_no_sql_reads_the_database_clock.
    ("now() (use clock.now_iso)", r"(?<![\w.])now\(\)"),
    ("AT TIME ZONE / ::date (Python bounds)", r"AT\s+TIME\s+ZONE|::date\b"),
    ("date_trunc / substr(col, 1, 10) (bucket in Python, install timezone)", r"date_trunc|substr\(\s*[\w.]+\s*,\s*1\s*,\s*10\s*\)"),
    ("EXTRACT(EPOCH) (julianday)", r"EXTRACT\s*\(\s*EPOCH"),
    ("make_interval (precomputed cutoff)", r"make_interval"),
    ("DISTINCT ON (row_number() = 1)", r"DISTINCT\s+ON\b"),
    ("= ANY(...) (json_each)", r"=\s*ANY\s*\("),
    ("ILIKE (FTS, or LIKE … COLLATE NOCASE for ASCII)", r"\bILIKE\b"),
    ("Postgres casts (CAST)", r"\w::(int|text|float8|numeric|bigint|date|jsonb?)\b"),
    ("NUMERIC / REAL money (integer cents)", r"\b(NUMERIC|DOUBLE\s+PRECISION)\b|value\s+REAL\b"),
    ("Json()/JSONB (json.dumps)", r"\bJson\(|\bJSONB\b"),
    ("psycopg2 (sqlite3.IntegrityError)", r"psycopg2"),
    ("%s placeholders (?)", r"[\"'][^\"'\n]*\bVALUES\s*\([^)]*%s|=\s*%s"),
    ("SERIAL (INTEGER PRIMARY KEY AUTOINCREMENT)", r"\b(BIG)?SERIAL\b"),
    ("TIMESTAMPTZ (canonical UTC text)", r"\bTIMESTAMPTZ\b"),
    ("GREATEST/LEAST (multi-argument max/min)", r"\b(GREATEST|LEAST)\s*\("),
]


def violations(text: str) -> list[str]:
    found = []
    for lineno, line in enumerate(text.splitlines(), 1):
        code = line.split("--", 1)[0] if line.lstrip().startswith("--") else line
        for name, pattern in CHECKLIST:
            if re.search(pattern, code, re.IGNORECASE):
                found.append(f"{lineno}: {name}: {line.strip()[:100]}")
    return found


def files() -> list[Path]:
    return sorted([*CRM.glob("*.py"), *CRM.glob("migrations/*.sql")])


def test_the_guard_reads_the_real_modules():
    names = {f.name for f in files()}
    assert {"deals.py", "router.py", "analytics.py", "20261101000000_crm_init.sql"} <= names


@pytest.mark.parametrize("bad", [
    "SELECT * FROM crm_deals WHERE id = %s FOR UPDATE",
    "cur.execute('UPDATE x SET a = %s', (1,))",
    "WHERE created_at > now() - make_interval(days => 7)",
    "SELECT date_trunc('day', created_at)",
    "SELECT substr(d.created_at, 1, 10) AS day",
    "SELECT DISTINCT ON (deal_id) *",
    "WHERE id = ANY(%s)",
    "WHERE title ILIKE ?",
    "SELECT value::float8",
    "value NUMERIC(12, 2)",
    "GREATEST(d.updated_at, x)",
    "import psycopg2",
])  # fmt: skip
def test_the_guard_flags_postgres(bad):
    assert violations(bad)


@pytest.mark.parametrize("good", [
    "SELECT * FROM crm_deals WHERE id IN (SELECT value FROM json_each(?))",
    "max(d.updated_at, coalesce(x, d.updated_at))",
    "value_cents INTEGER NOT NULL DEFAULT 0",
    "f'{k} = ?'",
    "-- a comment that mentions FOR UPDATE and now() is fine",
])  # fmt: skip
def test_the_guard_passes_sqlite(good):
    assert violations(good) == []


@pytest.mark.parametrize("path", files(), ids=lambda p: p.name)
def test_no_postgres_survives_the_port(path):
    assert violations(path.read_text(encoding="utf-8")) == []
