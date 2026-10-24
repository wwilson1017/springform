from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = (REPO_ROOT / "springform-version").read_text(encoding="utf-8").strip()
