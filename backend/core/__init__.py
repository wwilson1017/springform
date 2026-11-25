import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = (REPO_ROOT / "springform-version").read_text(encoding="utf-8").strip()
# The image's build arg (CI publish) or Railway's; "" when unknown.
# simplification: dev runs report no commit; upgrade path: read .git/HEAD when present.
COMMIT = os.environ.get("SPRINGFORM_COMMIT") or os.environ.get("SPRINGFORM_RAILWAY_COMMIT") or ""
