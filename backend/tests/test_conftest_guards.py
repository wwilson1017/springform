"""The shared fixtures' guards (the skip/skipif/xfail ban; no thread left running past its test's database),
on synthetic tests in an inner session and on this suite."""

import threading

from pytest import ExitCode

from backend.testing import fixtures

INNER_CONFTEST = "from backend.testing.fixtures import pytest_collection_modifyitems\n"
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
    # fmt: off
    for line in ("test_skipped: @pytest.mark.skip", "test_skipped_if: @pytest.mark.skipif",
                 "test_expected_to_fail: @pytest.mark.xfail"):
        result.stderr.fnmatch_lines([f"*test_suppressed.py::{line}"])
    # fmt: on


def test_clean_tests_and_allow_listed_ids_pass(pytester, monkeypatch):
    pytester.makeconftest(INNER_CONFTEST)
    pytester.makepyfile(test_clean=CLEAN)
    assert pytester.runpytest().ret == ExitCode.OK
    pytester.makepyfile(test_suppressed="import pytest\n\n@pytest.mark.skip\ndef test_skipped(): pass\n")
    monkeypatch.setattr(fixtures, "ALLOWED_SUPPRESSIONS", frozenset({"test_suppressed.py::test_skipped"}))
    assert pytester.runpytest().ret == ExitCode.OK


def test_the_ban_scanned_this_suite(request):
    assert request.config.stash[fixtures.CHECKED] >= len(request.session.items) >= 1  # -k deselects after the hook


def test_app_tests_are_collected(request):
    """Apps keep their tests in backend/apps/<slug>/tests/; the example app's run here with no conftest of their own."""
    assert "backend/apps" in request.config.getini("testpaths")


THREAD_CONFTEST = "from backend.testing.fixtures import _isolate\n"
LEFT_RUNNING = """
import threading

def test_leaves_a_thread_running():
    release = threading.Event()
    t = threading.Thread(target=release.wait, name="left-running", daemon=True)
    t.release = release
    t.start()

def test_never_runs(): pass
"""
ENDS_IN_TIME = """
import threading, time

def test_a_thread_that_ends_is_waited_for():
    threading.Thread(target=time.sleep, args=(0.05,), name="short").start()

def test_clean(): pass
"""


def test_a_thread_left_running_stops_the_run_and_names_the_test(pytester, monkeypatch):
    """#52: a thread still querying when its test's database closed crashed the whole run with SIGSEGV."""
    monkeypatch.setattr(fixtures, "THREAD_GRACE", 0.1)
    pytester.makeconftest(THREAD_CONFTEST)
    pytester.makepyfile(test_left=LEFT_RUNNING)
    try:
        result = pytester.runpytest()
        assert result.ret == ExitCode.INTERRUPTED
        result.stdout.fnmatch_lines(
            ["*test_left.py::test_leaves_a_thread_running left thread(s) running: left-running*"]
        )
        result.assert_outcomes(passed=1)  # the second test never ran
    finally:  # the inner run is in-process: release its thread so it does not outlive this test
        for t in threading.enumerate():
            if t.name == "left-running":
                getattr(t, "release").set()  # set by the inner run's conftest
                t.join()


def test_a_thread_that_ends_in_time_passes(pytester):
    pytester.makeconftest(THREAD_CONFTEST)
    pytester.makepyfile(test_ends=ENDS_IN_TIME)
    pytester.runpytest().assert_outcomes(passed=2)


def test_the_thread_guard_wraps_this_suite(request):
    assert "_isolate" in request.fixturenames
