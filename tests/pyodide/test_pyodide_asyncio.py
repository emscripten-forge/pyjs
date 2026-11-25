# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Derived from pyodide (src/tests/test_asyncio.py, release 314.0.8), modified for pyjs.
#
# Left out: nothing.
#
# Changes beyond the ones described in README.md:
# - pyodide lets the page run with `time.sleep` on the host between two
#   `selenium.run` calls. Here the test waits for the future the coroutine
#   yielded (`wait_done`).
# - the files fetched (pyodide: `console.html`, `pyodide-lock.json`) are files
#   of the test suite, served by the test driver.
# - the log of the page cannot be read from inside the page: the tests that
#   look into it capture `sys.stderr` / listen for unhandled rejections.
import asyncio
import contextlib
import gc
import io
from pathlib import Path

import pytest

import pyodide_helpers  # noqa: F401  (the JS helpers assert, assertThrows, ...)
from pyodide.code import eval_code_async, run_js
from pyodide.ffi import JSException

# a text file and a JSON file (an array) the test driver serves
TEXT_URL = "/tests/main.py"
TEXT = (Path(__file__).resolve().parent.parent / "main.py").read_text()
JSON_URL = "/tests/__files__.json"


async def run_js_async(code, timeout=30):
    """pyodide's `selenium.run_js(code)`: the code is the body of an async
    function. (`timeout`: only a guard against a promise that never settles.)"""
    return await asyncio.wait_for(run_js("(async () => {" + code + "\n})()"), timeout)


async def wait_done(future):
    """wait until the future a coroutine yielded is done (without consuming
    its result: the coroutine gets that)"""
    await asyncio.wait([future], timeout=30)
    assert future.done()


async def test_await_jsproxy():
    resolve = None

    def prom(res, rej):
        nonlocal resolve
        resolve = res

    from js import Promise
    from pyodide.ffi import create_once_callable

    p = Promise.new(create_once_callable(prom))

    async def temp():
        x = await p
        return x + 7

    resolve(10)
    c = temp()
    r = c.send(None)
    await wait_done(r)
    with pytest.raises(StopIteration, match="17"):
        c.send(r.result())


async def test_then_jsproxy():
    resolve = None
    reject = None

    def prom(res, rej):
        nonlocal resolve
        nonlocal reject
        resolve = res
        reject = rej

    from js import Promise
    from pyodide.ffi import create_once_callable

    result = None
    err = None
    finally_occurred = False

    def onfulfilled(value):
        nonlocal result
        result = value

    def onrejected(value):
        nonlocal err
        err = value

    def onfinally():
        nonlocal finally_occurred
        finally_occurred = True

    async def settled():
        # the callbacks of a settled promise run as microtasks: all of them
        # ran before the next task of the event loop (pyodide: time.sleep on
        # the host)
        await asyncio.sleep(0)

    p = Promise.new(create_once_callable(prom))
    p.then(onfulfilled, onrejected)
    resolve(10)
    await settled()
    assert result == 10
    assert err is None
    result = None

    p = Promise.new(create_once_callable(prom))
    p.then(onfulfilled, onrejected)
    reject(10)
    await settled()
    assert result is None
    assert err == 10
    err = None

    p = Promise.new(create_once_callable(prom))
    p.catch(onrejected)
    resolve(10)
    await settled()
    assert err is None

    p = Promise.new(create_once_callable(prom))
    p.catch(onrejected)
    reject(10)
    await settled()
    assert err == 10
    err = None

    p = Promise.new(create_once_callable(prom))
    p.finally_(onfinally)
    resolve(10)
    await settled()
    assert finally_occurred
    finally_occurred = False

    p = Promise.new(create_once_callable(prom))
    p.finally_(onfinally).catch(onrejected)  # node gets angry if we don't catch it!
    reject(10)
    await settled()
    assert finally_occurred
    finally_occurred = False
    assert err == 10
    err = None


async def test_await_fetch():
    from js import fetch

    async def test():
        response = await fetch(TEXT_URL)
        result = await response.text()
        return result

    c = test()
    r1 = c.send(None)
    await wait_done(r1)
    r2 = c.send(r1.result())
    await wait_done(r2)
    with pytest.raises(StopIteration) as excinfo:
        c.send(r2.result())
    assert excinfo.value.value == TEXT


async def test_await_error():
    run_js(
        """
        async function async_js_raises(){
            throw new Error("This is an error message!");
        }
        self.async_js_raises = async_js_raises;
        """
    )
    from js import async_js_raises

    async def test():
        c = await async_js_raises()
        return c

    c = test()
    r1 = c.send(None)
    await wait_done(r1)
    msg = "This is an error message!"
    with pytest.raises(JSException, match=msg):
        try:
            c.send(r1.result())
        finally:
            del async_js_raises
            run_js("delete self.async_js_raises")


def test_eval_code_async_simple():
    c = eval_code_async("1+92")
    with pytest.raises(StopIteration, match="93"):
        c.send(None)


def test_eval_code_async_dedent():
    indented_source = """
        1 + 1
    """

    # default (dedent=True): indented top-level code runs fine.
    c = eval_code_async(indented_source)
    with pytest.raises(StopIteration, match="2"):
        c.send(None)

    # dedent=False: mis-indented top-level code raises IndentationError.
    c = eval_code_async(indented_source, dedent=False)
    with pytest.raises(IndentationError):
        c.send(None)


async def test_eval_code_async_loop():
    async def slow_identity(i):
        await asyncio.sleep(0.1)
        return i

    c = eval_code_async(
        """
        tot = 0
        for i in range(10):
            tot += await slow_identity(i)
        tot
        """,
        globals=globals(),
        locals=locals(),
    )
    # pyodide (on the host): a new event loop and run_until_complete, which
    # cannot block in the browser
    fut = asyncio.ensure_future(c)
    await fut
    assert fut.result() == 45


async def test_eval_code_await_jsproxy():
    resolve = None

    def prom(res, rej):
        nonlocal resolve
        resolve = res

    from js import Promise
    from pyodide.ffi import create_once_callable

    p = Promise.new(create_once_callable(prom))
    from pyodide.code import eval_code_async

    c = eval_code_async(
        """
        x = await p
        x + 7
        """,
        globals={"p": p},
    )
    resolve(10)
    r = c.send(None)
    await wait_done(r)
    with pytest.raises(StopIteration, match="17"):
        c.send(r.result())


async def test_eval_code_await_fetch():
    from js import fetch
    from pyodide.code import eval_code_async

    c = eval_code_async(
        """
        response = await fetch(TEXT_URL)
        await response.text()
        """,
        globals={"fetch": fetch, "TEXT_URL": TEXT_URL},
    )
    r1 = c.send(None)
    await wait_done(r1)
    r2 = c.send(r1.result())
    await wait_done(r2)
    with pytest.raises(StopIteration) as excinfo:
        c.send(r2.result())
    assert excinfo.value.value == TEXT


async def test_eval_code_await_error():
    run_js(
        """
        async function async_js_raises(){
            console.log("Hello there???");
            throw new Error("This is an error message!");
        }
        self.async_js_raises = async_js_raises;
        """
    )
    try:
        from js import async_js_raises
        from pyodide.code import eval_code_async

        c = eval_code_async(
            """
            await async_js_raises()
            """,
            globals={"async_js_raises": async_js_raises},
        )
        r1 = c.send(None)
        await wait_done(r1)
        msg = "This is an error message!"
        with pytest.raises(JSException, match=msg):
            c.send(r1.result())
    finally:
        run_js("delete self.async_js_raises")


def test_ensure_future_memleak():
    # (in pyodide the check for leaked proxies after the test is the test)
    import asyncio

    from pyodide.code import run_js

    o = run_js("() => ({ xxx: 777 })")()

    async def test():
        return o

    asyncio.ensure_future(test())


# `pyodide._api.pyodide_code.eval_code_async` is the Python function
# `pyodide.code.eval_code_async`
EVAL_CODE_ASYNC_JS = """
    const pyodide_code = pyjs.pyimport("pyodide.code");
    const eval_code_async = pyodide_code.eval_code_async;
    pyodide_code.destroy();
"""


async def test_await_pyproxy_eval_async():
    assert (
        await run_js_async(
            EVAL_CODE_ASYNC_JS
            + """
            let c = eval_code_async("1+1");
            let result = await c;
            c.destroy();
            return result;
            """
        )
        == 2
    )

    assert (
        await run_js_async(
            EVAL_CODE_ASYNC_JS
            + """
            let finally_occurred = false;
            let c = eval_code_async("1+1");
            let result = await c.finally(() => { finally_occurred = true; });
            c.destroy();
            return [result, finally_occurred];
            """
        )
    ).to_py() == [2, True]

    assert (
        await run_js_async(
            EVAL_CODE_ASYNC_JS
            + """
            let finally_occurred = false;
            let err_occurred = false;
            let c = eval_code_async("raise ValueError('hi')");
            try {
                let result = await c.finally(() => { finally_occurred = true; });
            } catch(e){
                err_occurred = e.constructor.name === "PythonError";
            }
            c.destroy();
            return [finally_occurred, err_occurred];
            """
        )
    ).to_py() == [True, True]

    assert await run_js_async(
        EVAL_CODE_ASYNC_JS
        + """
        let c = eval_code_async("raise ValueError('hi')");
        try {
            return await c.catch(e => e.constructor.name === "PythonError");
        } finally {
            c.destroy();
        }
        """
    )

    assert await run_js_async(
        EVAL_CODE_ASYNC_JS
        + """
        let c = eval_code_async(`
            from js import fetch
            await (await fetch('%s')).json()
        `);
        let result = await c;
        c.destroy();
        return (!!result) && result.includes("main.py");
        """
        % JSON_URL
    )


async def test_await_pyproxy_async_def():
    assert await run_js_async(
        """
        let files = await pyjs.runPythonAsync(`
            from js import fetch
            async def temp():
                return await (await fetch('%s')).json()
            await temp()
        `);
        return (!!files.length) && files.includes("main.py");
        """
        % JSON_URL
    )


async def test_cancellation():
    from asyncio import ensure_future, sleep

    from js import fetch

    # pyodide looks for "InvalidStateError" in the log of the page: an error
    # in a callback of the fetch promise is an unhandled rejection
    rejections = run_js(
        """
        globalThis.__rejections = [];
        globalThis.__on_rejection = (event) => { __rejections.push(String(event.reason)); };
        addEventListener("unhandledrejection", __on_rejection);
        __rejections
        """
    )
    try:
        pending = []

        async def f():
            while True:
                pending.append(fetch(TEXT_URL))
                await pending[-1]

        fut = ensure_future(f())
        # (pyodide: sleep(0.01)) until f waits for a fetch
        for _ in range(1000):
            if pending:
                break
            await sleep(0)
        assert pending
        fut.cancel()
        # (pyodide: sleep(0.1)) until the fetch f waited for is done and its
        # callbacks ran
        await pending[-1]
        await sleep(0.1)
        assert "InvalidStateError" not in "\n".join(rejections.to_py())
    finally:
        run_js(
            """
            removeEventListener("unhandledrejection", __on_rejection);
            delete globalThis.__rejections;
            delete globalThis.__on_rejection;
            """
        )


async def test_uncaught_exception():
    import asyncio

    async def f():
        1 / 0  # noqa: B018

    # (pyodide reads the log of the page)
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        asyncio.create_task(f())
        await asyncio.sleep(0)
        gc.collect()

    log = stderr.getvalue()

    assert "Unhandled exception in event loop" in log
    assert "Traceback (most recent call last):" in log
    assert "test_pyodide_asyncio.py" in log and "in f" in log
    assert "ZeroDivisionError: division by zero" in log
