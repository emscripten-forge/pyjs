# Tests ported from pyodide

The test files in this directory are derived from the test suite of
[pyodide](https://github.com/pyodide/pyodide) (`src/tests/`, release
314.0.8) and adapted to pyjs. pyodide is licensed under the Mozilla Public
License 2.0; so are these files (see `LICENSE` in this directory). They were
modified: see below.

Why they are here: pyjs follows the API of pyodide / PEP 818, so pyodide's
tests are the best available description of how that API has to behave.

## What was changed

- pyodide runs each test body inside the browser from a pytest on the host
  (`@run_in_pyodide`, the `selenium` fixture). Here the whole pytest session
  runs inside the browser, so the decorator and the fixture are gone and the
  body is the test.
- Tests that drove the page from the host (`selenium.run_js(...)`,
  `selenium.run(...)`) became Python tests that run the same JavaScript with
  `run_js`. The JavaScript object `pyodide` of those snippets is `pyjs` here.
  `pyodide_helpers.py` provides the JavaScript helpers `assert`,
  `assertThrows` and `assertThrowsAsync` of pyodide's test plugin.
- Names: `JsProxy` -> `JSProxy`, `JsException` -> `JSException`, ... (the
  PEP 818 spelling); `pyodide.ffi` / `pyodide.code` are imported as such
  (pyjs provides them).
- hypothesis based tests only keep their explicit `@example` cases, as
  `pytest.mark.parametrize`.
- `blns.base64.json` is copied unchanged from pyodide's `src/tests/`. It is
  the "Big List of Naughty Strings" (strings that tend to break programs),
  base64 encoded; its own licence (MIT) is in `blns_LICENSE`.
- pyodide checks after every test that no proxy leaked. That check does not
  exist here.

## What is marked or left out

- A test for something pyjs does not have (yet) is kept and marked
  `@pytest.mark.xfail(reason="pyjs: ...")`, so that the list of differences
  to pyodide is visible in the test run.
- Tests of pyodide internals (its reference counting tables, package
  loading, `loadPyodide` options, ...) are left out. The comment at the top
  of each file lists them.
