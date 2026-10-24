"""The conftest's skip/skipif/xfail ban, on synthetic tests in an inner session and on this suite."""

from pytest import ExitCode

from backend.tests import conftest

INNER_CONFTEST = "from backend.tests.conftest import pytest_collection_modifyitems\n"
SUPPRESSED = """
import pytest

@pytest.mark.skip(reason="later")
def test_skipped(): pass

@pytest.mark.skipif(True, reason="never")
def test_skipped_if(): pass

@pytest.mark.xfail
def test_expected_to_fail(): assert False
"""
CLEAN = """
import pytest

@pytest.mark.parametrize("n", [1, 2])
def test_fine(n): assert n
"""


def test_suppression_markers_fail_collection(pytester):
    pytester.makeconftest(INNER_CONFTEST)
    pytester.makepyfile(test_suppressed=SUPPRESSED, test_clean=CLEAN)
    result = pytester.runpytest()
    assert result.ret == ExitCode.USAGE_ERROR
    for line in ("test_skipped: @pytest.mark.skip", "test_skipped_if: @pytest.mark.skipif",
                 "test_expected_to_fail: @pytest.mark.xfail"):
        result.stderr.fnmatch_lines([f"*test_suppressed.py::{line}"])


def test_clean_tests_and_allow_listed_ids_pass(pytester, monkeypatch):
    pytester.makeconftest(INNER_CONFTEST)
    pytester.makepyfile(test_clean=CLEAN)
    assert pytester.runpytest().ret == ExitCode.OK
    pytester.makepyfile(test_suppressed="import pytest\n\n@pytest.mark.skip\ndef test_skipped(): pass\n")
    monkeypatch.setattr(conftest, "ALLOWED_SUPPRESSIONS", frozenset({"test_suppressed.py::test_skipped"}))
    assert pytester.runpytest().ret == ExitCode.OK


def test_the_ban_scanned_this_suite(request):
    assert request.config.stash[conftest.CHECKED] >= len(request.session.items) >= 1  # -k deselects after the hook
