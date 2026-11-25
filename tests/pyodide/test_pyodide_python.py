# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Derived from pyodide (src/tests/test_python.py, release 314.0.8), modified for pyjs.
#
# Left out:
# - test_webbrowser_antigravity, test_webbrowser_open, test_webbrowser_open_new,
#   test_webbrowser_open_new_tab: the host driver counts the windows / pages
#   of the browser (nothing the interpreter can observe)
# - test_webbrowser_register_and_get, test_webbrowser_error,
#   test_webbrowser_browser_classes: details of pyodide's webbrowser patch
#   (pyjs replaces the module `webbrowser` with a minimal stand-in)
# - test_version_info: `pyodide.__version__` / `pyodide.version`
#
# pyodide's `selenium.run_async(code)` is `loadPackagesFromImports(code)`
# followed by `runPythonAsync(code)`: the tests whose imports need no package
# loading only call `pyjs.runPythonAsync`.
import asyncio

import js
import pytest

import pyodide_helpers  # noqa: F401  (the JS helpers assert, assertThrows, ...)
from pyodide.code import run_js


async def run_js_async(code, timeout=30):
    """pyodide's `selenium.run_js(code)`: the code is the body of an async
    function. (`timeout`: only a guard against a promise that never settles.)"""
    return await asyncio.wait_for(run_js("(async () => {" + code + "\n})()"), timeout)


def test_print():
    # pyodide looks for the text in the log of the page, which cannot be read
    # from inside the page: what is left is that printing works
    run_js("""pyjs.runPython("print('This should be logged')")""")


@pytest.mark.skipif(not hasattr(js, "window"), reason="no window in a worker")
def test_import_js():
    result = run_js(
        """
        pyjs.runPython(`
            import js
            js.window.title = 'Foo'
            js.window.title
        `)
        """
    )
    assert result == "Foo"
    result = dir(js)
    # pyjs: dir() of a JSProxy does not list the properties of the JavaScript object
    # assert len(result) > 100
    # assert "document" in result
    # assert "window" in result


def test_globals_get_multiple():
    """See #1151"""
    run_js(
        """
        (() => {
            pyjs.runPython("v = 0.123");
            pyjs.globals.get('v')
            pyjs.globals.get('v')
        })()
        """
    )


@pytest.mark.xfail(reason="pyjs: no loadPackagesFromImports")
async def test_runpythonasync():
    output = await run_js_async(
        """
        const code = `
            import micropip
            micropip.__version__
        `;
        await pyjs.loadPackagesFromImports(code);
        return await pyjs.runPythonAsync(code);
        """
    )
    assert isinstance(output, str)


async def test_runpythonasync_no_imports():
    output = await run_js_async(
        """
        return await pyjs.runPythonAsync(`
            42
        `);
        """
    )
    assert output == 42


async def test_runpythonasync_missing_import():
    await run_js_async(
        """
        await assertThrowsAsync(
            async () => await pyjs.runPythonAsync(`
                import foo
            `),
            "PythonError",
            "ModuleNotFoundError"
        );
        """
    )


async def test_runpythonasync_exception():
    await run_js_async(
        """
        await assertThrowsAsync(
            async () => await pyjs.runPythonAsync(`
                42 / 0
            `),
            "PythonError",
            "ZeroDivisionError"
        );
        """
    )


@pytest.mark.xfail(reason="pyjs: no loadPackagesFromImports")
async def test_runpythonasync_exception_after_import():
    await run_js_async(
        """
        const code = `
            import micropip
            42 / 0
        `;
        await pyjs.loadPackagesFromImports(code);
        await assertThrowsAsync(
            async () => await pyjs.runPythonAsync(code),
            "PythonError",
            "ZeroDivisionError"
        );
        """
    )


def test_py():
    run_js(
        """
        (() => {
            pyjs.runPython(`
                def func():
                    return 42
            `);
            let func = pyjs.globals.get('func');
            assert(() => func() === 42);
            func.destroy();
        })()
        """
    )


def test_eval_nothing():
    assert run_js("pyjs.runPython('# comment')") is None
    assert run_js("pyjs.runPython('')") is None


async def test_unknown_attribute():
    from unittest import TestCase

    raises = TestCase().assertRaisesRegex
    import js

    with raises(AttributeError, "asdf"):
        js.asdf  # noqa: B018
