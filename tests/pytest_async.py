"""Async tests under pytest, inside the browser.

(Written for pyjs. pyodide's test suite does not need this: it runs pytest
on the host and sends each test body into the browser, so nothing of it is
used here.)

THE PROBLEM. pytest runs a test session with one blocking call,
`pytest.main()`. An `async def` test only makes progress when control goes
back to the event loop. In the browser the event loop is the browser's own,
and Python cannot block and "run it until the test is done" from inside a
call (that is what `asyncio.run` does elsewhere). So pytest cannot run an
async test while `pytest.main()` is on the stack.

THE WAY AROUND IT. Split it in two phases:

1. During `pytest.main()`: pytest collects everything and runs the
   synchronous tests as usual. For an async test this plugin only *creates*
   the coroutine (which runs nothing yet) and puts it aside. pytest prints
   such a test as DEFERRED.
2. After `pytest.main()` returned, `tests/main.py` (which is itself async and
   can await) calls `run_deferred()`: the coroutines are awaited one after
   the other and their outcome is printed and counted.

So async tests are ordinary pytest tests: collected by name, selectable with
markers, usable with `@pytest.mark.parametrize`, `skipif` and `xfail`.

THE LIMITATION. Whatever pytest does *around* a test call happens in phase 1,
before the coroutine ran: a fixture is set up and torn down again before the
test body executes. Fixtures that only provide a value are fine; fixtures
with cleanup (and `monkeypatch`, `tmp_path`, ...) cannot be used by async
tests. Clean up inside the test with try / finally.
"""

import asyncio
import collections
import inspect
import time
import traceback

import pytest

# (pytest's own evaluation of `@pytest.mark.xfail(...)`: not public API, but
# the only place that knows all the rules of the marker's arguments)
from _pytest.skipping import evaluate_xfail_marks


class AsyncTests:
    """The pytest plugin, see the module docstring. Also counts the outcomes
    of all tests (sync and async) for the summary in `counts`."""

    def __init__(self, timeout=300):
        # seconds one async test may take. A test waiting for something that
        # never happens would otherwise hang the whole run, and all results
        # with it. (Only a hang guard: far above what any test needs.)
        self.timeout = timeout
        # the async tests put aside: (test id, coroutine)
        self._deferred = []
        self._deferred_ids = set()
        # outcome ("passed", "failed", "skipped", ...) -> number of tests
        self.counts = collections.Counter()

    # -- phase 1: called by pytest ------------------------------------------
    @pytest.hookimpl(tryfirst=True)
    def pytest_pyfunc_call(self, pyfuncitem):
        """pytest asks every plugin "who calls this test function?". For an
        `async def` test: we do, by creating its coroutine and keeping it for
        phase 2. Returning True tells pytest the call is taken care of; None
        (for normal functions) lets pytest call it itself."""
        function = pyfuncitem.obj
        if not inspect.iscoroutinefunction(function):
            return None
        # the arguments the test function asks for (parameters of
        # `parametrize`, values of fixtures), as pytest prepared them
        arguments = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
        # Is the test marked as "expected to fail"? Needed in phase 2. pytest
        # itself evaluates the marker (its condition, `raises=`, `strict=`):
        # None, or an object with `.raises` and `.strict`.
        # (not with --runxfail: then xfail tests are run like normal ones)
        xfail = None if pyfuncitem.config.option.runxfail else evaluate_xfail_marks(pyfuncitem)
        self._deferred.append((pyfuncitem.nodeid, function(**arguments), xfail))
        self._deferred_ids.add(pyfuncitem.nodeid)
        return True

    def pytest_report_teststatus(self, report, config):
        """how pytest prints a test: a deferred one did not pass, it has not
        run yet"""
        if report.when == "call" and report.nodeid in self._deferred_ids:
            return "deferred", "D", "DEFERRED (async, runs after the sync tests)"
        return None

    def pytest_runtest_logreport(self, report):
        """count the outcome of every test. A test has three steps (setup,
        call, teardown): its result is the one of `call`, unless setup or
        teardown did not pass (a failing fixture, a `skipif`)."""
        if report.nodeid in self._deferred_ids and report.when == "call":
            return  # counted in phase 2
        if report.when == "call" or report.outcome != "passed":
            outcome = report.outcome
            if hasattr(report, "wasxfail"):
                # a test marked xfail. pytest sets `wasxfail` in both cases:
                # it failed as expected (reported as "skipped"), or it
                # PASSED although a failure was expected ("passed"): the
                # marker is stale, which must be visible in the counts.
                outcome = "xpassed" if report.outcome == "passed" else "xfailed"
            self.counts[outcome] += 1

    # -- phase 2: called by tests/main.py -----------------------------------
    async def _await_with_timeout(self, coroutine):
        """Await one test, at most `self.timeout` seconds: its result, or
        its exception, or a TimeoutError.

        The test runs as its own asyncio task. `asyncio.wait` (not
        `wait_for`): `wait_for` waits until the cancelled task has really
        ended, and a test stuck in `pyjs.run_sync` (suspended, not at an
        `await`) never reacts to its cancellation."""
        task = asyncio.ensure_future(coroutine)
        done, _ = await asyncio.wait({task}, timeout=self.timeout)
        if not done:
            task.cancel()
            raise TimeoutError(f"the test did not finish within {self.timeout} s")
        return task.result()

    async def run_deferred(self):
        """await the async tests put aside in phase 1, one after the other"""
        if not self._deferred:
            return
        print(f"\n{'=' * 30} async tests ({len(self._deferred)}) {'=' * 30}", flush=True)
        failures = []
        for nodeid, coroutine, xfail in self._deferred:
            start = time.time()
            try:
                await self._await_with_timeout(coroutine)
                if xfail is None:
                    outcome = "passed"
                elif xfail.strict:
                    # `xfail(strict=True)`: passing is an error
                    outcome = "failed"
                    failures.append((nodeid, "[XPASS(strict)] the test passed, but is marked xfail(strict=True)"))
                else:
                    # passing although a failure was expected is reported,
                    # but is no error, as in pytest
                    outcome = "xpassed"
            except pytest.skip.Exception as skipped:
                # `pytest.skip(...)` called inside the test
                outcome = f"skipped ({skipped})"
            except pytest.xfail.Exception:
                # `pytest.xfail(...)` called inside the test
                outcome = "xfailed"
            except BaseException as error:
                # `@pytest.mark.xfail`: the expected failure (with `raises=`:
                # only an exception of that type is the expected one)
                if xfail is not None and (xfail.raises is None or isinstance(error, xfail.raises)):
                    outcome = "xfailed"
                else:
                    outcome = "failed"
                    failures.append((nodeid, traceback.format_exc()))
            self.counts[outcome.split()[0]] += 1
            print(f"{nodeid} {outcome.upper()} [{time.time() - start:.2f}s]", flush=True)
        for nodeid, text in failures:
            print(f"\n{'_' * 20} {nodeid} {'_' * 20}\n{text}", flush=True)
        self._deferred = []
