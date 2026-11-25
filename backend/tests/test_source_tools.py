"""core_code_search, core_code_list and core_code_read: only the allow-listed source is readable,
nothing leaves the code root, and the real tree (the copy the image ships) is what they read."""

import pytest

from backend.core import REPO_ROOT
from backend.core.errors import Invalid
from backend.core.source import tools as code


@pytest.fixture
def tree(tmp_path, monkeypatch):
    (tmp_path / "backend/apps/crm/docs").mkdir(parents=True)
    (tmp_path / "backend/apps/crm/docs/merge.md").write_text("# Merge\nMerge two people into one.\n")
    (tmp_path / "backend/__pycache__").mkdir()
    (tmp_path / "backend/__pycache__/x.pyc").write_text("merge")
    (tmp_path / "frontend/src").mkdir(parents=True)
    (tmp_path / "frontend/src/App.tsx").write_text("export const merge = 1\n")
    (tmp_path / "frontend/package.json").write_text('{"merge": 1}')
    (tmp_path / "data").mkdir()
    (tmp_path / "data/springform.sqlite").write_text("merge")
    (tmp_path / ".env").write_text("SECRET=merge")
    (tmp_path / "README.md").write_text("merge readme\n")
    (tmp_path / "uv.lock").write_text("merge")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("merge")
    (tmp_path / "backend/escape.py").symlink_to(outside)
    (tmp_path / "backend/to_data.py").symlink_to(tmp_path / "data/springform.sqlite")
    monkeypatch.setattr(code, "ROOT", tmp_path)
    return tmp_path


def test_search_sees_only_the_allow_list(tree):
    out = code.search("MERGE")
    assert out["hits"] == [
        "README.md:1: merge readme",
        "backend/apps/crm/docs/merge.md:1: # Merge",
        "backend/apps/crm/docs/merge.md:2: Merge two people into one.",
        "frontend/src/App.tsx:1: export const merge = 1",
    ]
    assert code.search("merge", "frontend/src")["total"] == 1
    assert code.search("nothing here")["note"].startswith("No matches")


def test_list_shows_readable_entries_only(tree):
    assert code.list_dir("") == {"path": ".", "folders": ["backend/", "frontend/"], "files": ["README.md"]}
    assert code.list_dir("frontend") == {"path": "frontend", "folders": ["src/"], "files": []}
    assert code.list_dir("backend")["files"] == []  # both symlinks lead outside the allow-list


@pytest.mark.parametrize(
    "path",
    ["../x", "/etc/passwd", "~/x", ".env", "data/springform.sqlite", "uv.lock", "frontend/package.json",
     "backend/__pycache__/x.pyc", "backend/escape.py", "backend/to_data.py"],
)  # fmt: skip
def test_read_refuses_anything_outside_the_allow_list(tree, path):
    with pytest.raises(Invalid):
        code.read(path)


def test_read_numbers_lines_and_says_when_it_cut(tree, monkeypatch):
    (tree / "backend/long.py").write_text("".join(f"line {n}\n" for n in range(1, 11)))
    monkeypatch.setattr(code, "MAX_LINES", 4)
    out = code.read("backend/long.py", start_line=3)
    assert (out["text"], out["end_line"], out["total_lines"]) == ("3: line 3\n4: line 4\n5: line 5\n6: line 6", 6, 10)
    assert "start_line" in out["note"]
    assert "note" not in code.read("backend/long.py", start_line=7)


def test_the_real_tree_is_what_they_read():
    assert code.ROOT == REPO_ROOT
    hits = code.search("REPO_ROOT = ", "backend/core/__init__.py")["hits"]
    assert hits and hits[0].startswith("backend/core/__init__.py:")
    assert "source/" in code.list_dir("backend/core")["folders"]
    assert not any(h.startswith(".") for h in code.list_dir("")["files"])
