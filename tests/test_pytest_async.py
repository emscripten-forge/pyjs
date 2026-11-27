"""The test runner itself (pytest_async.py): how outcomes are counted.

A small pytest session with one test per outcome is run inside a test, with
the same plugin tests/main.py uses, and its counts are checked. Why this
matters: a runner that reports "xfailed" for a test that passes, or "passed"
for one that never ran, hides exactly the problems tests exist for.
"""

import contextlib
import io
import sys
import tempfile
from pathlib import Path

import pytest

from pytest_async import AsyncTests

SAMPLE = '''
import asyncio

import pytest


def test_sync_pass():
    pass


def test_sync_fail():
    assert False


@pytest.mark.xfail(reason="really fails")
def test_sync_xfail():
    assert False


@pytest.mark.xfail(reason="stale: the test passes")
def test_sync_xpass():
    pass


async def test_async_pass():
    await asyncio.sleep(0)


async def test_async_fail():
    await asyncio.sleep(0)
    assert False


@pytest.mark.xfail(reason="really fails")
async def test_async_xfail():
    assert False


@pytest.mark.xfail(reason="stale: the test passes")
async def test_async_xpass():
    pass


@pytest.mark.xfail(False, reason="the condition is false: a normal test")
async def test_async_xfail_condition_false():
    assert False


@pytest.mark.xfail(raises=KeyError, reason="only a KeyError is expected")
async def test_async_xfail_other_exception():
    raise ValueError("not the expected one")


async def test_async_calls_xfail():
    pytest.xfail("decided inside the test")


async def test_async_calls_skip():
    pytest.skip("decided inside the test")


async def test_async_hangs():
    await asyncio.Future()  # never done
'''

EXPECTED = {
    # test_sync_pass, test_async_pass
    "passed": 2,
    # test_sync_fail, test_async_fail, test_async_xfail_condition_false,
    # test_async_xfail_other_exception, test_async_hangs (timeout)
    "failed": 5,
    # test_sync_xfail, test_async_xfail, test_async_calls_xfail
    "xfailed": 3,
    # test_sync_xpass, test_async_xpass
    "xpassed": 2,
    # test_async_calls_skip
    "skipped": 1,
}


async def test_outcomes_are_counted_right():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "test_runner_sample.py"
        path.write_text(SAMPLE)
        # (a short timeout: test_async_hangs must be reported as failed, not
        # hang the run)
        plugin = AsyncTests(timeout=0.5)
        # The output of the sample session is not shown: its FAILED lines
        # are intended, and would look like failures of the real run.
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                exit_code = pytest.main(
                    ["-q", "-p", "no:faulthandler", "-p", "no:cacheprovider", "--rootdir", directory, str(path)],
                    plugins=[plugin],
                )
                await plugin.run_deferred()
        finally:
            sys.modules.pop("test_runner_sample", None)
    assert dict(plugin.counts) == EXPECTED, f"{dict(plugin.counts)}\n{output.getvalue()}"
    # (pytest's own exit code: 1 = some tests failed)
    assert int(exit_code) == 1
