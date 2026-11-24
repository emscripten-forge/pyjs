"""The JavaScript tests (`js/test_*.js`) as pytest tests.

Each JS file is an ES module; every function it exports as
`export async function test_...(pyjs)` is one test: it gets the pyjs Module
of the page and fails by throwing. Here they are turned into one parametrized
pytest test, so that they show up in the same run and summary as the Python
tests.
"""

import os
import re
from pathlib import Path

import js
import pytest

JS_DIR = Path(__file__).resolve().parent / "js"

# `import(url)` as function (the import statement cannot be called from python)
_import_module = js.Function("url", "return import(url);")


def _js_tests():
    """(file name, function name) of every test function of the JS files.

    The names are read from the source text: importing a JS module is
    asynchronous, and pytest collects tests synchronously."""
    tests = []
    for path in sorted(JS_DIR.glob("test_*.js")):
        for name in re.findall(r"^export\s+async\s+function\s+(test_\w+)", path.read_text(), re.MULTILINE):
            tests.append((path.name, name))
    return tests


@pytest.mark.parametrize("file,name", _js_tests(), ids=lambda value: value)
async def test_js(file, name):
    # (the browser caches the module: importing it for every test is cheap)
    module = await _import_module(f"{os.environ['PYJS_TESTS_URL']}/js/{file}")
    # the pyjs Module of this page (set by the page: pyjs_test_driver/web/harness.js)
    await getattr(module, name)(js.globalThis.pyjs)
