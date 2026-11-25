# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Derived from pyodide (src/tests/test_pyodide.py, release 314.0.8), modified for pyjs.
#
# Left out:
# - test_unpack_archive: the arguments of pyodide's `unpackArchive(buffer,
#   format, options)` (pyjs' npm package has `unpackArchive({url, path})`,
#   tested in tests/test_archives.py)
# - test_promise_check: `pyodide._api.isPromise` (internal)
# - test_check_interrupt_no_gil: calls CPython's C API through `_module`
#   (`_PyEval_SaveThread`)
# - test_docstrings_a, test_docstrings_b: `_pyodide._core_docs`,
#   `_pyodide.docstring` (internal)
# - test_restore_state: `pyodide._api.saveState` / `restoreState` (internal)
# - test_fatal_error, test_exit_error, test_reentrant_fatal,
#   test_weird_fatals: fatal errors, the page is unusable afterwards
# - test_js_stackframes: the JavaScript frames pyodide adds to Python
#   tracebacks, with the file names of pyodide
# - test_env, test_args, test_args_OO, test_fs_init,
#   test_compat_null_to_none, test_loadPyodide_relative_index_url,
#   test_custom_python_stdlib_URL, test_csp, test_static_import: options of
#   `loadPyodide`, need a fresh page
# - test_relative_index_url, test_index_url_calculation_source_map,
#   test_default_index_url_calculation_node: run node on the host
# - test_version_variable, test_abiVersion_variable, test_python_version:
#   versions of pyodide (`pyodide.version`, `pyodide._api`)
# - test_default_sys_path, test_sys_path0: the file system layout of pyodide
# - test_module_not_found_note: `_pyodide._importhook` (internal), the
#   packages of the pyodide distribution
# - test_windows_to_linux_path_finder,
#   test_windows_to_linux_path_finder_edge_cases,
#   test_windows_to_linux_path_finder_registration,
#   test_windows_to_linux_path_import: windows paths, `_pyodide._importhook`
# - test_pickle_internal_error: pickling an exception from the browser to
#   the host (pytest-pyodide), `pyodide.ffi.InternalError`
# - test_hiwire_invalid_ref: hiwire (internal)
# - test_lockfile_api: the lock file of pyodide
#
# Changes beyond the ones described in README.md:
# - test_pyimport1 / test_pyimport3 call the Python function behind
#   `pyodide.pyimport` in pyodide (`_pyodide._base.pyimport_impl`); here they
#   call `pyjs.pyimport`.
# - the files fetched (pyodide: `pyodide-lock.json`) are files of the test
#   suite, served by the test driver.
import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import dedent
from typing import Any

import pytest

import pyodide_helpers  # noqa: F401  (the JS helpers assert, assertThrows, ...)
from pyodide.code import eval_code, run_js
from pyodide.ffi import JSProxy

# a JSON file (an array of file names) the test driver serves
JSON_URL = "/tests/__files__.json"

NO_INTERRUPTS = "pyjs: no interrupts (setInterruptBuffer / checkInterrupt)"
NO_DEDENT = (
    "pyjs: no option dedent of runPython / runPythonAsync ({dedent: false} is ignored, "
    "'    1 + 1' gives 2; pyodide raises IndentationError)"
)


def to_py(value):
    """arrays / objects as list / dict, like the values pyodide's host gets"""
    return value.to_py() if isinstance(value, JSProxy) else value


def run_js_sync(code):
    """pyodide's `selenium.run_js(code)` for code that awaits nothing: the
    code is the body of a function"""
    return to_py(run_js("(() => {" + code + "\n})()"))


async def run_js_async(code, timeout=30):
    """pyodide's `selenium.run_js(code)`: the code is the body of an async
    function. (`timeout`: only a guard against a promise that never settles.)"""
    return to_py(await asyncio.wait_for(run_js("(async () => {" + code + "\n})()"), timeout))


# `pyodide.pyimport` as Python function (pyodide: `_pyodide._base.pyimport_impl`)
pyimport_impl = run_js("(name) => pyjs.pyimport(name)")


@pytest.mark.xfail(reason="pyjs: no find_imports")
def test_find_imports():
    from pyodide.code import find_imports

    res = find_imports(
        """
        import numpy as np
        from scipy import sparse
        import matplotlib.pyplot as plt
        """
    )
    assert set(res) == {"numpy", "scipy", "matplotlib", "matplotlib.pyplot"}

    # If there is a syntax error in the code, find_imports should return empty
    # list.
    res = find_imports(
        """
        import numpy as np
        from scipy import sparse
        import matplotlib.pyplot as plt
        for x in [1,2,3]
        """
    )
    assert res == []


def test_ffi_import_star():
    exec("from pyodide.ffi import *", {})


@pytest.mark.xfail(reason="pyjs: no pyodide.console")
def test_pyimport1():
    assert pyimport_impl("pyodide").__name__ == "pyodide"
    assert pyimport_impl("pyodide.console").__name__ == "pyodide.console"
    assert pyimport_impl("pyodide.console.BANNER").startswith("Python ")


def test_pyimport2():
    run_js_sync(
        """
        let platform = pyjs.pyimport("platform");
        // (pyodide: "wasm32" only)
        assert(() => ["wasm32", "wasm64"].includes(platform.machine()));
        assert(() => !pyjs.globals.has("platform"))
        assertThrows(() => pyjs.pyimport("platform;"), "PythonError", "ModuleNotFoundError: No module named 'platform;'");
        platform.destroy();
        """
    )


def test_pyimport3():
    with TemporaryDirectory() as tempdir:
        Path(tempdir, "aaa").mkdir()
        Path(tempdir, "aaa", "bbb.py").write_text("ccc = 1")
        sys.path.insert(0, tempdir)
        try:
            aaa = pyimport_impl("aaa")
            pyimport_impl("aaa.bbb")
            del aaa.bbb.ccc

            # case 1 unload parent module
            del sys.modules["aaa"]
            assert pyimport_impl("aaa.bbb") == eval_code("from aaa import bbb; bbb")

            # case 2 delete child module
            del aaa.bbb
            assert pyimport_impl("aaa.bbb") == eval_code("from aaa import bbb; bbb")

            # case 3 recover deleted value
            with pytest.raises(ModuleNotFoundError):
                pyimport_impl("aaa.bbb.ccc")
            del sys.modules["aaa.bbb"]
            assert pyimport_impl("aaa.bbb.ccc") == 1
        finally:
            sys.path.remove(tempdir)
            sys.modules.pop("aaa", None)
            sys.modules.pop("aaa.bbb", None)


@pytest.mark.xfail(reason="pyjs: no CodeRunner / should_quiet")
def test_code_runner():
    from pyodide.code import CodeRunner, should_quiet

    assert should_quiet("1+1;")
    assert not should_quiet("1+1#;")
    assert not should_quiet("5-2  # comment with trailing semicolon ;")

    # Normal usage
    assert CodeRunner("1+1").compile().run() == 2
    assert CodeRunner("1+1\n1+1").compile().run() == 2
    assert CodeRunner("x + 7").compile().run({"x": 3}) == 10

    # Use constants > 255 so they are stored in co_consts rather than loaded
    # via LOAD_SMALL_INT (Python 3.14+ loads ints 0-255 directly via opcode).
    cr = CodeRunner("x + 700")

    # Ast transform: change "x + 700" to "x * 300 + 700"
    import ast

    l = cr.ast.body[0].value.left  # type: ignore[attr-defined]
    cr.ast.body[0].value.left = ast.BinOp(  # type: ignore[attr-defined]
        left=l, op=ast.Mult(), right=ast.Constant(value=300)
    )
    assert cr.compile().run({"x": 3}) == 1600

    # Code transform: change "x * 300 + 700" to "x * 400 + 500"
    assert cr.code
    co_consts = cr.code.co_consts
    new_consts = tuple({300: 400, 700: 500}.get(c, c) for c in co_consts)
    cr.code = cr.code.replace(co_consts=new_consts)
    assert cr.run({"x": 4}) == 2100


@pytest.mark.xfail(reason="pyjs: no CodeRunner / should_quiet")
def test_code_runner_mode():
    from codeop import PyCF_DONT_IMPLY_DEDENT  # type: ignore[attr-defined]

    from pyodide.code import CodeRunner

    assert CodeRunner("1+1\n1+1", mode="exec").compile().run() == 2
    with pytest.raises(SyntaxError, match="invalid syntax"):
        CodeRunner("1+1\n1+1", mode="eval").compile().run()
    with pytest.raises(
        SyntaxError,
        match="multiple statements found while compiling a single statement",
    ):
        CodeRunner("1+1\n1+1", mode="single").compile().run()
    with pytest.raises(SyntaxError, match="invalid syntax"):
        CodeRunner(
            "def f():\n  1", mode="single", flags=PyCF_DONT_IMPLY_DEDENT
        ).compile().run()


def test_eval_code():
    ns: dict[str, Any] = {}
    assert (
        eval_code(
            """
        def f(x):
            return 2*x + 5
        f(77)
    """,
            ns,
        )
        == 2 * 77 + 5
    )
    assert ns["f"](7) == 2 * 7 + 5

    assert eval_code("(x:=4)", ns) == 4
    assert ns["x"] == 4
    assert eval_code("x=7", ns) is None
    assert ns["x"] == 7

    # default return_mode ('last_expr'), semicolon
    assert eval_code("1+1;", ns) is None
    assert eval_code("1+1#;", ns) == 2
    assert eval_code("5-2  # comment with trailing semicolon ;", ns) == 3
    assert eval_code("4//2\n", ns) == 2
    assert eval_code("2**1\n\n", ns) == 2
    assert eval_code("4//2;\n", ns) is None
    assert eval_code("2**1;\n\n", ns) is None

    # 'last_expr_or_assign' return_mode, semicolon
    assert eval_code("1 + 1", ns, return_mode="last_expr_or_assign") == 2
    assert eval_code("x = 1 + 1", ns, return_mode="last_expr_or_assign") == 2
    assert eval_code("a = 5 ; a += 1", ns, return_mode="last_expr_or_assign") == 6
    assert eval_code("a = 5 ; a += 1;", ns, return_mode="last_expr_or_assign") is None
    assert (
        eval_code("l = [1, 1, 2] ; l[0] = 0", ns, return_mode="last_expr_or_assign")
        is None
    )
    assert eval_code("a = b = 2", ns, return_mode="last_expr_or_assign") == 2

    # 'none' return_mode, (useless) semicolon
    assert eval_code("1 + 1", ns, return_mode="none") is None
    assert eval_code("x = 1 + 1", ns, return_mode="none") is None
    assert eval_code("a = 5 ; a += 1", ns, return_mode="none") is None
    assert eval_code("a = 5 ; a += 1;", ns, return_mode="none") is None
    assert eval_code("l = [1, 1, 2] ; l[0] = 0", ns, return_mode="none") is None

    # with 'quiet_trailing_semicolon' set to False
    assert eval_code("1+1;", ns, quiet_trailing_semicolon=False) == 2
    assert eval_code("1+1#;", ns, quiet_trailing_semicolon=False) == 2
    assert (
        eval_code(
            "5-2  # comment with trailing semicolon ;",
            ns,
            quiet_trailing_semicolon=False,
        )
        == 3
    )
    assert eval_code("4//2\n", ns, quiet_trailing_semicolon=False) == 2
    assert eval_code("2**1\n\n", ns, quiet_trailing_semicolon=False) == 2
    assert eval_code("4//2;\n", ns, quiet_trailing_semicolon=False) == 2
    assert eval_code("2**1;\n\n", ns, quiet_trailing_semicolon=False) == 2


def test_eval_code_dedent():
    indented_source = """
        print("hello world")
    """

    # default (dedent=True) strips the common leading whitespace so the
    # indented block runs fine.
    eval_code(indented_source, {})

    # dedent=False compiles the source as-is, so an indented top-level
    # statement raises IndentationError just like it would with a plain
    # `python -c` invocation.
    with pytest.raises(IndentationError):
        eval_code(indented_source, {}, dedent=False)

    # dedent=False still works for source that is already flush with
    # column 0.
    assert eval_code("1 + 1", {}, dedent=False) == 2


def test_eval_code_locals():
    globals: dict[str, Any] = {}
    eval_code("x=2", globals, {})
    with pytest.raises(NameError):
        eval_code("x", globals, {})

    locals: dict[str, Any] = {}
    eval_code("import sys; sys.getrecursionlimit()", globals, locals)
    with pytest.raises(NameError):
        eval_code("sys.getrecursionlimit()", globals, {})
    eval_code("sys.getrecursionlimit()", globals, locals)

    eval_code(
        "from importlib import invalidate_caches; invalidate_caches()", globals, locals
    )
    with pytest.raises(NameError):
        eval_code("invalidate_caches()", globals, globals)
    eval_code("invalidate_caches()", globals, locals)

    # See https://github.com/pyodide/pyodide/issues/3578
    with pytest.raises(NameError):
        eval_code("print(self)")

    res = eval_code(
        """
        var = "Hello"
        def test():
            return var
        test()
        """
    )
    assert res == "Hello"


@pytest.mark.xfail(reason="pyjs: no relaxed_call / relaxed_wrap")
def test_relaxed_call():
    from pyodide.code import relaxed_call

    assert relaxed_call(int, "7") == 7

    def f1(a, b):
        return [a, b]

    assert relaxed_call(f1, 1, 2) == [1, 2]
    assert relaxed_call(f1, 1, 2, 3) == [1, 2]
    assert relaxed_call(f1, 1, b=7) == [1, 7]
    assert relaxed_call(f1, a=2, b=7) == [2, 7]
    assert relaxed_call(f1, 1, b=7, c=9) == [1, 7]
    assert relaxed_call(f1, 1, 2, 3, c=9) == [1, 2]
    with pytest.raises(TypeError, match="missing a required argument: 'b'"):
        relaxed_call(f1, 1)
    with pytest.raises(TypeError, match="multiple values for argument 'b'"):
        relaxed_call(f1, 1, 2, b=3)

    def f2(a, b=7):
        return [a, b]

    assert relaxed_call(f2, 1, 2) == [1, 2]
    assert relaxed_call(f2, 1, 2, 3) == [1, 2]
    assert relaxed_call(f2, 1, b=7) == [1, 7]
    assert relaxed_call(f2, a=2, b=7) == [2, 7]
    assert relaxed_call(f2, 1, b=7, c=9) == [1, 7]
    assert relaxed_call(f2, 1, 2, 3, c=9) == [1, 2]
    assert relaxed_call(f2, 1) == [1, 7]
    with pytest.raises(TypeError, match="missing a required argument: 'a'"):
        relaxed_call(f2)

    def f3(a, *args, b=7):
        return [a, args, b]

    assert relaxed_call(f3, 1, 2) == [1, (2,), 7]
    assert relaxed_call(f3, 1, 2, 3) == [1, (2, 3), 7]
    assert relaxed_call(f3, 1, b=7) == [1, (), 7]
    assert relaxed_call(f3, a=2, b=7) == [2, (), 7]
    assert relaxed_call(f3, 1, b=7, c=9) == [1, (), 7]
    assert relaxed_call(f3, 1, 2, 3, c=9) == [1, (2, 3), 7]
    assert relaxed_call(f3, 1) == [1, (), 7]

    def f4(a, /, *args, b=7):
        return [a, args, b]

    # Since Python 3.13.3, the TypeError message for missing positional-only arguments has changed.
    # See: https://github.com/python/cpython/pull/130192
    with pytest.raises(TypeError, match=r"missing .* argument: 'a'"):
        relaxed_call(f4, a=2, b=7)

    def f5(a, *args, b=7, **kwargs):
        return [a, args, b, kwargs]

    assert relaxed_call(f5, 1, 2, 3, 4, b=7, c=9) == [1, (2, 3, 4), 7, {"c": 9}]


@pytest.mark.xfail(reason="pyjs: no relaxed_call / relaxed_wrap")
def test_relaxed_wrap():
    from pyodide.code import relaxed_wrap

    with pytest.raises(TypeError, match="Cannot wrap function"):
        relaxed_wrap(int)

    @relaxed_wrap
    def f1(a, b):
        return [a, b]

    assert f1(1, 2) == [1, 2]
    assert f1(1, 2, 3) == [1, 2]
    assert f1(1, b=7) == [1, 7]
    assert f1(a=2, b=7) == [2, 7]
    assert f1(1, b=7, c=9) == [1, 7]
    assert f1(1, 2, 3, c=9) == [1, 2]
    with pytest.raises(TypeError, match="missing a required argument: 'b'"):
        f1(1)
    with pytest.raises(TypeError, match="multiple values for argument 'b'"):
        f1(1, 2, b=3)

    @relaxed_wrap
    def f2(a, b=7):
        return [a, b]

    assert f2(1, 2) == [1, 2]
    assert f2(1, 2, 3) == [1, 2]
    assert f2(1, b=7) == [1, 7]
    assert f2(a=2, b=7) == [2, 7]
    assert f2(1, b=7, c=9) == [1, 7]
    assert f2(1, 2, 3, c=9) == [1, 2]
    assert f2(1) == [1, 7]
    with pytest.raises(TypeError, match="missing a required argument: 'a'"):
        f2()

    @relaxed_wrap
    def f3(a, *args, b=7):
        return [a, args, b]

    assert f3(1, 2) == [1, (2,), 7]
    assert f3(1, 2, 3) == [1, (2, 3), 7]
    assert f3(1, b=7) == [1, (), 7]
    assert f3(a=2, b=7) == [2, (), 7]
    assert f3(1, b=7, c=9) == [1, (), 7]
    assert f3(1, 2, 3, c=9) == [1, (2, 3), 7]
    assert f3(1) == [1, (), 7]

    @relaxed_wrap
    def f4(a, /, *args, b=7):
        return [a, args, b]

    with pytest.raises(TypeError, match=r"missing .* argument: 'a'"):
        f4(a=2, b=7)

    @relaxed_wrap
    def f5(a, *args, b=7, **kwargs):
        return [a, args, b, kwargs]

    assert f5(1, 2, 3, 4, b=7, c=9) == [1, (2, 3, 4), 7, {"c": 9}]


def test_dup_pipe():
    # See https://github.com/emscripten-core/emscripten/issues/14640
    import os

    [fdr1, fdw1] = os.pipe()
    fdr2 = os.dup(fdr1)
    fdw2 = os.dup2(fdw1, 50)
    # Closing any of fdr, fdr2, fdw, or fdw2 will currently destroy the pipe.
    # This bug is fixed upstream:
    # https://github.com/emscripten-core/emscripten/pull/14685
    s1 = b"some stuff"
    s2 = b"other stuff to write"
    os.write(fdw1, s1)
    assert os.read(fdr2, 100) == s1
    os.write(fdw2, s2)
    assert os.read(fdr1, 100) == s2


def test_dup_temp_file():
    # See https://github.com/emscripten-core/emscripten/issues/15012
    import os
    from tempfile import TemporaryFile

    tf = TemporaryFile(buffering=0)
    fd1 = os.dup(tf.fileno())
    os.dup2(tf.fileno(), 50)
    s = b"hello there!"
    tf.write(s)
    tf2 = open(fd1, "w+")
    assert tf2.tell() == len(s)
    # This next assertion actually demonstrates a bug in dup: the correct value
    # to return should be b"".
    assert os.read(fd1, 50) == b""
    tf2.seek(1)
    assert tf.tell() == 1
    assert tf.read(100) == b"ello there!"


def test_dup_stdout():
    # Test redirecting stdout using low level os.dup operations.
    # This sort of redirection is used in pytest.
    import os
    import sys
    from tempfile import TemporaryFile

    tf = TemporaryFile(buffering=0)
    save_stdout = os.dup(sys.stdout.fileno())
    os.dup2(tf.fileno(), sys.stdout.fileno())
    print("hi!!")
    print("there...")
    assert tf.tell() == len("hi!!\nthere...\n")
    os.dup2(save_stdout, sys.stdout.fileno())
    print("not captured")
    os.dup2(tf.fileno(), sys.stdout.fileno())
    print("captured")
    assert tf.tell() == len("hi!!\nthere...\ncaptured\n")
    os.dup2(save_stdout, sys.stdout.fileno())
    os.close(save_stdout)
    tf.seek(0)
    assert tf.read(1000).decode() == "hi!!\nthere...\ncaptured\n"


def test_monkeypatch_eval_code():
    try:
        run_js_sync(
            """
            pyjs.runPython(`
                import pyodide
                old_eval_code = pyodide.code.eval_code
                x = 3
                def eval_code(code, globals=None, locals=None):
                    return [globals["x"], old_eval_code(code, globals, locals)]
                pyodide.code.eval_code = eval_code
            `);
            """
        )
        assert run_js_sync("return pyjs.runPython('x = 99; 5')") == [3, 5]
        assert run_js_sync("return pyjs.runPython('7')") == [99, 7]
    finally:
        run_js_sync(
            """
            pyjs.runPython(`
                pyodide.code.eval_code = old_eval_code
            `);
            """
        )


@pytest.mark.xfail(reason=NO_INTERRUPTS)
def test_keyboard_interrupt():
    x = run_js_sync(
        """
        let x = new Int8Array(1);
        pyjs.setInterruptBuffer(x);
        self.triggerKeyboardInterrupt = function(){
            x[0] = 2;
        }
        try {
            pyjs.runPython(`
                from js import triggerKeyboardInterrupt
                for x in range(100000):
                    if x == 2000:
                        triggerKeyboardInterrupt()
            `);
        } catch(e){}
        pyjs.setInterruptBuffer(undefined);
        return pyjs.globals.get('x');
        """
    )
    assert 2000 < x < 2500


async def test_run_python_async_toplevel_await():
    await run_js_async(
        """
        await pyjs.runPythonAsync(`
            from js import fetch
            resp = await fetch("%s")
            json = (await resp.json()).to_py()
            assert "main.py" in json
        `);
        """
        % JSON_URL
    )


async def test_run_python_proxy_leak():
    await run_js_async(
        """
        pyjs.runPython("")
        await pyjs.runPythonAsync("")
        """
    )


def test_run_python_last_exc():
    run_js_sync(
        """
        try {
            pyjs.runPython("x = ValueError(77); raise x");
        } catch(e){}
        pyjs.runPython(`
            import sys
            assert sys.last_exc is x
            assert sys.last_value is x
            assert sys.last_type is type(x)
            assert sys.last_traceback is x.__traceback__
        `);
        """
    )


@pytest.mark.xfail(reason=NO_INTERRUPTS)
def test_check_interrupt():
    # First make sure checkInterrupt works when interrupt buffer is undefined.
    # It should just do nothing in this case.
    run_js_sync(
        """
        pyjs.setInterruptBuffer(undefined);
        pyjs.checkInterrupt();
        """
    )

    assert run_js_sync(
        """
        let buffer = new Uint8Array(1);
        let x = 0;
        pyjs.setInterruptBuffer(buffer);
        function test(){
            buffer[0] = 2;
            pyjs.checkInterrupt();
            x = 1;
        }
        self.test = test;
        let err;
        try {
            pyjs.runPython(`
                from js import test;
                try:
                    test();
                finally:
                    del test
            `);
        } catch(e){
            err = e;
        }
        return x === 0 && err.message.includes("KeyboardInterrupt");
        """
    )

    assert run_js_sync(
        """
        let buffer = new Uint8Array(1);
        pyjs.setInterruptBuffer(buffer);
        buffer[0] = 2;
        let err_code = 0;
        for(let i = 0; i < 1000; i++){
            err_code = err_code || pyjs._PyErr_CheckSignals();
        }
        let err_occurred = pyjs._PyErr_Occurred();
        console.log({err_code, err_occurred});
        pyjs._PyErr_Clear();
        return buffer[0] === 0 && err_code === -1 && err_occurred !== 0;
        """
    )


@pytest.mark.xfail(reason=NO_INTERRUPTS)
def test_check_interrupt_custom_signal_handler():
    try:
        run_js_sync(
            """
            pyjs.runPython(`
                import signal
                interrupt_occurred = False
                def signal_handler(*args):
                    global interrupt_occurred
                    interrupt_occurred = True
                signal.signal(signal.SIGINT, signal_handler)
                None
            `);
            """
        )
        run_js_sync(
            """
            let buffer = new Uint8Array(1);
            let x = 0;
            pyjs.setInterruptBuffer(buffer);
            function test(){
                buffer[0] = 2;
                pyjs.checkInterrupt();
                x = 1;
            }
            self.test = test;
            let err;
            pyjs.runPython(`
                interrupt_occurred = False
                from js import test
                test()
                assert interrupt_occurred == True
                del test
            `);
            """
        )
        assert run_js_sync(
            """
            pyjs.runPython(`
                interrupt_occurred = False
            `);
            let buffer = new Uint8Array(1);
            pyjs.setInterruptBuffer(buffer);
            buffer[0] = 2;
            let err_code = 0;
            for(let i = 0; i < 1000; i++){
                err_code = err_code || pyjs._PyErr_CheckSignals();
            }
            let interrupt_occurred = pyjs.globals.get("interrupt_occurred");

            return buffer[0] === 0 && err_code === 0 && interrupt_occurred;
            """
        )
    finally:
        # Restore signal handler
        run_js_sync(
            """
            pyjs.runPython(`
                import signal
                signal.signal(signal.SIGINT, signal.default_int_handler)
                None
            `);
            """
        )


async def test_async_leak():
    assert 0 == await run_js_async(
        """
        pyjs.runPython(`d = 888.888`);
        pyjs.runPython(`async def test(): return d`);
        async function test(){
            let t = pyjs.runPython(`test()`);
            await t;
            t.destroy();
        }
        await test();
        let init_refcount = pyjs.runPython(`from sys import getrefcount; getrefcount(d)`);
        await test(); await test(); await test(); await test();
        let new_refcount = pyjs.runPython(`getrefcount(d)`);
        return new_refcount - init_refcount;
        """
    )


def test_run_python_js_error():
    run_js_sync(
        """
        function throwError(){
            throw new Error("blah!");
        }
        self.throwError = throwError;
        pyjs.runPython(`
            from js import throwError
            from unittest import TestCase
            from pyodide.ffi import JSException
            raises = TestCase().assertRaisesRegex
            with raises(JSException, "blah!"):
                throwError()
        `);
        """
    )


def test_run_python_dom_error():
    import pytest

    from js import DOMException
    from pyodide.ffi import JSException

    with pytest.raises(JSException, match="oops"):
        raise DOMException.new("oops")


def test_run_python_locals():
    run_js_sync(
        """
        let dict = pyjs.globals.get("dict");
        let locals = dict([["x", 7]]);
        let globals = dict([["x", 5], ["y", 29]]);
        dict.destroy();
        let result = pyjs.runPython("z = 13; x + y", {locals, globals});
        assert(() => locals.get("z") === 13);
        assert(() => locals.has("x"));
        let result2 = pyjs.runPython("del x; x + y", {locals, globals});
        assert(() => !locals.has("x"));
        assert(() => result === 7 + 29);
        assert(() => result2 === 5 + 29);
        locals.destroy();
        globals.destroy();
        """
    )


@pytest.mark.xfail(reason=NO_DEDENT)
def test_run_python_dedent():
    run_js_sync(
        """
        // default: indented top-level code is dedented before running.
        let result = pyjs.runPython("    1 + 1\\n");
        assert(() => result === 2);

        // dedent: false leaves mis-indented top-level code as-is, so it
        // raises IndentationError like a normal Python interpreter would.
        let raised = false;
        try {
            pyjs.runPython("    1 + 1\\n", { dedent: false });
        } catch (e) {
            raised = true;
            assert(() => e.message.includes("IndentationError"));
        }
        assert(() => raised);
        """
    )


@pytest.mark.xfail(reason=NO_DEDENT)
async def test_run_python_async_dedent():
    await run_js_async(
        """
        // default: indented top-level code is dedented before running.
        let result = await pyjs.runPythonAsync("    1 + 1\\n");
        assert(() => result === 2);

        // dedent: false leaves mis-indented top-level code as-is, so it
        // raises IndentationError like a normal Python interpreter would.
        let raised = false;
        try {
            await pyjs.runPythonAsync("    1 + 1\\n", { dedent: false });
        } catch (e) {
            raised = true;
            assert(() => e.message.includes("IndentationError"));
        }
        assert(() => raised);
        """
    )


def test_create_once_callable():
    import sys

    from pytest import raises

    from pyodide.code import run_js
    from pyodide.ffi import JSException, create_once_callable

    destroyed = False

    class Square:
        def __call__(self, x):
            return x * x

        def __del__(self):
            nonlocal destroyed
            destroyed = True

    f = Square()
    assert sys.getrefcount(f) == 1
    proxy = create_once_callable(f)
    assert sys.getrefcount(f) == 2

    call7 = run_js("(f) => f(7)")
    assert call7(proxy) == 49
    assert sys.getrefcount(f) == 1
    with raises(JSException, match="can only be called once"):
        call7(proxy)
    del f
    assert destroyed


def test_create_proxy():
    from pyodide.code import run_js
    from pyodide.ffi import create_proxy

    [testAddListener, testCallListener, testRemoveListener] = run_js(
        """
        function testAddListener(f){
            self.listener = f;
        }
        function testCallListener(f){
            return self.listener();
        }
        function testRemoveListener(f){
            return self.listener === f;
        }
        [testAddListener, testCallListener, testRemoveListener]
        """
    )

    destroyed = False

    class Test:
        def __call__(self):
            return 7

        def __del__(self):
            nonlocal destroyed
            destroyed = True

    f = Test()
    import sys

    assert sys.getrefcount(f) == 1
    proxy = create_proxy(f)
    assert sys.getrefcount(f) == 2
    assert proxy() == 7
    testAddListener(proxy)
    assert sys.getrefcount(f) == 2
    assert testCallListener() == 7
    assert sys.getrefcount(f) == 2
    assert testCallListener() == 7
    assert sys.getrefcount(f) == 2
    assert testRemoveListener(proxy)
    assert sys.getrefcount(f) == 2
    proxy.destroy()
    assert sys.getrefcount(f) == 1
    destroyed = False
    del f
    assert destroyed


@pytest.mark.xfail(reason="pyjs: no create_proxy(capture_this=)")
def test_create_proxy_capture_this():
    from pyodide.code import run_js
    from pyodide.ffi import create_proxy

    o = run_js("({})")

    def f(self):
        assert self == o

    o.f = create_proxy(f, capture_this=True)
    run_js("(o) => { o.f(); o.f.destroy(); }")(o)


def test_create_proxy_roundtrip():
    from pyodide.code import run_js
    from pyodide.ffi import JSDoubleProxy, create_proxy

    f = {}  # type: ignore[var-annotated]
    o = run_js("({})")
    o.f = create_proxy(f, roundtrip=True)
    assert isinstance(o.f, JSDoubleProxy)
    assert o.f.unwrap() is f
    o.f.destroy()
    o.f = create_proxy(f, roundtrip=False)
    assert o.f is f
    run_js("(o) => { o.f.destroy(); }")(o)


def test_return_destroyed_value():
    import pytest

    from pyodide.code import run_js
    from pyodide.ffi import JSException, create_proxy

    f = run_js("(function(x){ return x; })")
    p = create_proxy([])  # type: ignore[var-annotated]
    p.destroy()
    # (the message of pyodide: "Object has already been destroyed")
    with pytest.raises(JSException, match="This proxy was destroyed"):
        f(p)


def test_reentrant_error():
    caught = run_js_sync(
        """
        function raisePythonKeyboardInterrupt(){
            pyjs.globals.get("pyfunc")();
        }
        // (for `from js import`: the function has to be a global)
        self.raisePythonKeyboardInterrupt = raisePythonKeyboardInterrupt;
        let caught = false;
        try {
            pyjs.runPython(`
                def pyfunc():
                    raise KeyboardInterrupt
                from js import raisePythonKeyboardInterrupt
                try:
                    raisePythonKeyboardInterrupt()
                except Exception as e:
                    pass
            `);
        } catch(e){
            caught = true;
        }
        return caught;
        """
    )
    assert caught


def test_weird_throws():
    """Throw strange Javascript garbage and make sure we survive."""
    run_js(
        """
        self.funcs = {
            null(){ throw null; },
            undefined(){ throw undefined; },
            obj(){ throw {}; },
            obj_null_proto(){ throw Object.create(null); },
            string(){ throw "abc"; },
            func(){ throw self.funcs.func; },
            number(){ throw 12; },
            bigint(){ throw 12n; },
        };
        """
    )
    from unittest import TestCase

    from js import funcs
    from pyodide.ffi import JSException

    raises = TestCase().assertRaises
    # pyodide also checks its messages for the thrown values ("A value of
    # type object with tag [object Null] was thrown as an error!", ...) and
    # gets the functions from `funcs.object_entries()`
    names = ["null", "undefined", "obj", "obj_null_proto", "string", "func", "number", "bigint"]
    for name in names:
        f = getattr(funcs, name)
        with raises(JSException):
            f()


def test_restore_error():
    # See PR #1816.
    run_js_sync(
        """
        self.f = function(){
            pyjs.runPython(`
                err = Exception('hi')
                raise err
            `);
        }
        pyjs.runPython(`
            from js import f
            import sys
            try:
                f()
            except Exception as e:
                assert err == e
                assert e == sys.last_exc
                assert e == sys.last_value
            finally:
                del err
        `);
        // pyjs: not checked (pyodide internals): sys.getrefcount(sys.last_exc) == 3
        """
    )


def test_run_js():
    from unittest import TestCase

    from pyodide.code import run_js

    raises = TestCase().assertRaises

    with raises(TypeError, msg="argument should have type 'string' not type 'int'"):
        run_js(3)  # type: ignore[arg-type]

    assert run_js("(x)=> x+1")(7) == 8
    assert run_js("[1,2,3]")[2] == 3
    run_js("globalThis.x = 77")
    from js import x  # type: ignore[attr-defined]

    assert x == 77


def test_pickle_jsexception():
    import pickle

    from pyodide.code import run_js

    pickle.dumps(run_js("new Error('hi');"))


def test_raises_jsexception():
    from pyodide.ffi import JSException

    def raise_jsexception():
        from pyodide.code import run_js

        run_js("throw new Error('hi');")

    # (pyodide: the exception is pickled to the host; its text there is
    # "Error: hi", here the message of the error)
    with pytest.raises(JSException, match="hi"):
        raise_jsexception()


def test_importhook_called_from_pytest():
    """
    Whenever importlib itself resolves `import a.b`, it splits on the . and
    first imports `a` and then `a.b`. However, pytest does not, it calls
    `find_spec("a.b")` directly here:
    https://github.com/pytest-dev/pytest/blob/ea0fa639445ae08616edd2c15189a1a76168f018/src/_pytest/pathlib.py#L693-L698

    This previously could lead to KeyError being raised in `JsFinder`.
    """
    import sys

    def _import_module_using_spec(module_name):
        """Modeled on a fragment of _pytest.pathlib._import_module_using_spec"""
        for meta_importer in sys.meta_path:
            meta_importer.find_spec(module_name, [])

    # Assertion: This should not raise KeyError.
    _import_module_using_spec("a.b")


def test_python_error():
    [msg, ty] = run_js_sync(
        """
        try {
            pyjs.runPython("raise TypeError('oops')");
        } catch(e) {
            return [e.message, e.type];
        }
        """
    )
    assert msg.endswith("TypeError: oops\n")
    assert ty == "TypeError"


@pytest.mark.xfail(
    reason="pyjs differs: with {filename: 'a.py'} the traceback names a.py but shows no source "
    "lines (f2() / raise ... are missing) and has an extra frame of pyjs/code.py"
)
@pytest.mark.parametrize("run_python", ["pyjs.runPython", "await pyjs.runPythonAsync"])
async def test_runpython_filename(run_python):
    msg = await run_js_async(
        """
        try {
            %s(`
                def f1():
                    f2()

                def f2():
                    raise Exception("oops")

                f1()
            `, {filename: "a.py"});
        } catch(e) {
            return e.message
        }
        """
        % run_python
    )
    expected = dedent(
        """\
        File "a.py", line 3, in f1
          f2()

        File "a.py", line 6, in f2
          raise Exception("oops")
          ^^^^^^^^^^^^^^^
        """
    ).strip()

    assert dedent("\n".join(msg.splitlines()[-7:-1])) == expected
    msg = await run_js_async(
        """
        let f1;
        try {
            f1 = pyjs.globals.get("f1");
            f1();
        } catch(e) {
            console.log(e);
            return e.message;
        } finally {
            f1.destroy();
        }
        """
    )
    assert dedent("\n".join(msg.splitlines()[1:-1])) == expected


def test_system_exit():
    """Make sure nothing weird happens when we throw SystemExit"""
    for _ in range(3):
        run_js_sync(
            """
            assertThrows(
                () =>
                    pyjs.runPython(`
                        exit(1)
                    `),
                "PythonError",
                "SystemExit: 1",
            );
            """
        )


async def test_bug_4861():
    """In version 0.26.1, there was a regression that makes this raise
    "KeyError: '__builtins__'".

    I don't really understand what this reproducer does, what the problem was,
    or why the fix prevents the problem.
    """
    import collections

    from pyodide.code import run_js

    class ChainMap(collections.ChainMap, dict):  # type:ignore[misc, type-arg]
        pass

    def g(x):
        return eval("x()", ChainMap({}, {"x": x}))

    await g(run_js("async () => {}"))
