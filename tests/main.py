"""The pyjs test suite, run inside the browser.

The test driver (`pyjs_test_driver`) writes this directory to `/tests` in the
emscripten file system of a page with an initialized pyjs and awaits
`main(options)`.

Everything is one pytest run over `test_*.py`:

* synchronous tests: plain pytest
* `async def` tests: collected by pytest, awaited afterwards (pytest cannot
  await in the browser: `pytest_async.py` explains how that works)
* JavaScript tests (`js/test_*.js`): each exported `test_*` function is one
  pytest test (`test_js.py`)

options (from the driver): `disable_jspi` (test like in a browser without
JSPI, with the same build), `tests_url` (url of this directory, for the JS
modules), `filter` (a pytest `-k` expression: run only matching tests, e.g.
`pyjs_test_driver run <page> --option filter=test_proxy_types`), `file` (run
only this file or directory, relative to this one: `--option
file=pyodide/test_pyodide_jsproxy.py`), `runxfail` (run tests marked xfail
like normal ones, to see their errors: `--option runxfail=1`).
"""

import os
import sys
import time
from pathlib import Path

import pyjs

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # `helpers`, `pytest_async`


async def main(options):
    """run all tests, return a summary dict: `ok`, the number of tests per
    outcome (`passed`, `failed`, `skipped`, ...), `seconds`"""
    import pytest
    from pytest_async import AsyncTests

    if options.get("disable_jspi"):
        pyjs.core._disable_jspi()
    print("JSPI enabled:", pyjs.jspi_enabled(), flush=True)
    os.chdir(HERE)
    os.environ["NO_COLOR"] = "1"
    # where the browser can fetch the JS test modules from (test_js.py)
    os.environ["PYJS_TESTS_URL"] = options["tests_url"]

    start = time.time()
    plugin = AsyncTests()
    # -s: show print output right away (the console of the page is the log)
    # -p no:...: plugins that need what a browser does not have (signals, a
    # writable cache directory)
    # what to run: everything, or only one file / directory (option `file`,
    # relative to this directory)
    target = HERE / options["file"] if options.get("file") else HERE
    args = ["-s", "-vv", "-p", "no:faulthandler", "-p", "no:cacheprovider", str(target)]
    if options.get("filter"):
        # only the tests matching this pytest `-k` expression
        args += ["-k", options["filter"]]
    if options.get("runxfail"):
        # run tests marked xfail like normal ones (to see why they fail)
        args += ["--runxfail"]
    exit_code = pytest.main(args, plugins=[plugin])
    await plugin.run_deferred()

    summary = dict(plugin.counts)
    summary["seconds"] = round(time.time() - start, 1)
    # pytest's exit code covers what is no test outcome: errors while
    # collecting, a broken conftest, ... (0: all passed, 1: tests failed)
    summary["ok"] = int(exit_code) == 0 and not summary.get("failed") and not summary.get("error")
    print(f"\n{summary}", flush=True)
    return summary
