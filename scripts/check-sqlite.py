"""Assert that Python's sqlite3 module loads the pinned SQLite, with FTS5 and JSON, and that
zoneinfo has timezone data. Run at image build time by the Dockerfile.

Usage: python scripts/check-sqlite.py 3.51.3
"""

import sqlite3
import sys
import zoneinfo

want = sys.argv[1]
conn = sqlite3.connect(":memory:")
version = conn.execute("select sqlite_version()").fetchone()[0]
options = sorted(row[0] for row in conn.execute("pragma compile_options"))
assert version == want, f"sqlite3 loads SQLite {version}, want {want}"
assert "ENABLE_FTS5" in options, "FTS5 is not compiled in"
conn.execute("create virtual table t using fts5(body)")
assert conn.execute("""select json_extract('{"a": 1}', '$.a')""").fetchone()[0] == 1
zoneinfo.ZoneInfo("America/Chicago")
print(f"SQLite {version}: fts5 and json ok; compile options: {' '.join(options)}")
