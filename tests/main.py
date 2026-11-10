"""The pyjs test suite, run inside the browser.

The test driver (`pyjs_test_driver`) writes this directory to `/tests` in the
emscripten file system of a page with an initialized pyjs and awaits
`main(options)`. Runs, in this order:

1. JavaScript tests: `js/test_*.js` (ES modules, every exported `test_*`
   function is called with the pyjs Module)
2. async Python tests: `async/test_*.py` (every `async def test_*`, own runner:
   pytest cannot await in the browser, the event loop cannot be blocked)
3. sync Python tests: `sync/test_*.py` via pytest

options (from the driver): `disable_jspi` (test like in a browser without
JSPI, with the same build), `tests_url` (url of this directory, for the JS
modules).
"""

import collections
import importlib.util
import inspect
import os
import sys
import time
import traceback
from pathlib import Path

import pyjs

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # `helpers`


def section(title):
    """a visible separator in the test output"""
    print(f"{'=' * 40}\n{title}\n{'=' * 40}", flush=True)


async def run_js_tests(tests_url):
    """import every js/test_*.js module and await its `test_*` functions"""
    js_import = pyjs.js.Function("url", "return import(url)")
    js_pyjs = pyjs.js.globalThis.pyjs  # set by the page (the page contract)
    counts = collections.Counter()
    for path in sorted((HERE / "js").glob("test_*.js")):
        module = await js_import(f"{tests_url}/js/{path.name}")
        for name in pyjs.js.Object.keys(module):
            if not str(name).startswith("test_"):
                continue
            print(f"JS: {path.name}::{name}", flush=True)
            try:
                await getattr(module, str(name))(js_pyjs)
                counts["passed"] += 1
            except Exception:
                traceback.print_exc()
                counts["failed"] += 1
    return dict(counts)


def load_module(path):
    """import a test file by path (`async` is a keyword: no package imports)"""
    spec = importlib.util.spec_from_file_location(f"async_tests_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def run_async_tests():
    """await every `async def test_*` in async/test_*.py"""
    counts = collections.Counter()
    for path in sorted((HERE / "async").glob("test_*.py")):
        module = load_module(path)
        for name, fn in vars(module).items():
            if not (name.startswith("test_") and inspect.iscoroutinefunction(fn)):
                continue
            print(f"ASYNC: {path.name}::{name}", flush=True)
            try:
                await fn()
                counts["passed"] += 1
            except Exception:
                traceback.print_exc()
                counts["failed"] += 1
    return dict(counts)


class _PytestCounter:
    """pytest plugin: counts the outcomes for the summary"""

    def __init__(self):
        self.counts = collections.Counter()

    def pytest_runtest_logreport(self, report):
        if report.when == "call" or report.outcome != "passed":
            outcome = "xfailed" if hasattr(report, "wasxfail") else report.outcome
            self.counts[outcome] += 1


def run_sync_tests():
    """the sync tests via pytest (inside the browser, not on the host)"""
    import pytest

    os.environ["NO_COLOR"] = "1"
    counter = _PytestCounter()
    exit_code = pytest.main(
        ["-s", "-vv", "-p", "no:faulthandler", "-p", "no:cacheprovider", str(HERE / "sync")],
        plugins=[counter],
    )
    return dict(counter.counts, exit_code=int(exit_code))


async def main(options):
    """run all tests, return a summary dict (`ok` + counts per kind)"""
    if options.get("disable_jspi"):
        pyjs.core._disable_jspi()
    print("JSPI enabled:", pyjs.jspi_enabled(), flush=True)
    os.chdir(HERE)

    t0 = time.time()
    summary = {}
    section("JS TESTS")
    summary["js"] = await run_js_tests(options["tests_url"])
    section("ASYNC TESTS")
    summary["async"] = await run_async_tests()
    section("SYNC TESTS (pytest)")
    summary["sync"] = run_sync_tests()
    summary["seconds"] = round(time.time() - t0, 1)
    summary["ok"] = (
        not summary["js"].get("failed")
        and not summary["async"].get("failed")
        and summary["sync"]["exit_code"] == 0
    )
    return summary
