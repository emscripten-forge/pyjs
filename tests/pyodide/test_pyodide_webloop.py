# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Derived from pyodide (src/tests/test_webloop.py and
# src/tests/test_webloop_webworker.py, release 314.0.8), modified for pyjs.
#
# Left out:
# - test_call_later_skips_scheduling_for_infinite_delay: patches internals of
#   pyodide's webloop module (`scheduleCallback`, `_MAX_TIMEOUT_MS`)
# - test_inprogress: internals of pyodide's WebLoop (`_in_progress`,
#   `_no_in_progress_handler`, `_keyboard_interrupt_handler`, ...)
#
# Changes beyond the ones described in README.md:
# - tests that only use `pyodide.runPythonAsync` to run async Python code
#   (test_cancel_handle, test_run_in_executor) have that code as body.
# - test_zero_timeout / test_webworker_zero_timeout2 measure the time of 1000
#   `asyncio.sleep(0)` in pyodide. Here they check what makes it fast: no
#   `setTimeout` is used (no assertions on timing).
# - the log of the page cannot be read from inside the page: the tests that
#   look into it capture `sys.stderr`.
import asyncio
import contextlib
import gc
import io
import json

import js
import pytest

import pyodide_helpers  # noqa: F401  (the JS helpers assert, assertThrows, ...)
from pyodide.code import run_js

# a text file the test driver serves
TEXT_URL = "/tests/main.py"

IN_WORKER = not hasattr(js, "window")

NO_ASYNCGEN_TRACKING = (
    "pyjs: no async generator tracking by the WebLoop: shutdown_asyncgens() exists, "
    "but does not close the async generators started in the test (their finally does not run)"
)


async def run_js_async(code, timeout=30):
    """pyodide's `selenium.run_js(code)`: the code is the body of an async
    function. (`timeout`: only a guard against a promise that never settles.)"""
    return await asyncio.wait_for(run_js("(async () => {" + code + "\n})()"), timeout)


async def run_with_resolve(code):
    await run_js_async(
        f"""
        try {{
            let promise = new Promise((resolve) => self.resolve = resolve);
            pyjs.runPython({json.dumps(code)});
            await promise;
        }} finally {{
            delete self.resolve;
        }}
        """
    )


class CountSetTimeout:
    """counts the `setTimeout` calls of the event loop while active"""

    def __init__(self, loop):
        self.loop = loop
        self.delays_ms = []

    def __enter__(self):
        self._orig = self.loop._set_timeout

        def counting(callback, ms):
            self.delays_ms.append(ms)
            return self._orig(callback, ms)

        self.loop._set_timeout = counting
        return self

    def __exit__(self, *exc):
        self.loop._set_timeout = self._orig


# Safari: `call_soon` falls back to `setTimeout` (as in pyodide)
needs_zero_timeout = pytest.mark.skipif(
    asyncio.get_event_loop()._macrotask_queue is None,
    reason="this browser uses setTimeout as a fallback for 0ms delay",
)


async def test_asyncio_sleep():
    # test asyncio.sleep
    await run_with_resolve(
        """
        import asyncio
        from js import resolve
        async def sleep_task():
            print('start sleeping for 1s')
            await asyncio.sleep(1)
            print('sleeping done')
            resolve()
        asyncio.ensure_future(sleep_task())
        None
        """,
    )


async def test_asyncio_sleep_overflowing_delay():
    import asyncio

    import pytest

    task = asyncio.ensure_future(asyncio.sleep(1e9))
    await asyncio.sleep(0.1)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # (pyodide also checks that node did not log a TimeoutOverflowWarning)


async def test_call_later_negative_delay():
    import asyncio

    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    loop.call_later(-1, fut.set_result, "later")
    assert await fut == "later"

    fut = loop.create_future()
    loop.call_at(loop.time() - 1, fut.set_result, "at")
    assert await fut == "at"


async def test_cancel_handle():
    import asyncio

    loop = asyncio.get_event_loop()
    exc = []

    def exception_handler(loop, context):
        exc.append(context)

    loop.set_exception_handler(exception_handler)
    try:
        await asyncio.wait_for(asyncio.sleep(1), 2)
    finally:
        loop.set_exception_handler(None)
    assert not exc


async def test_new_event_loop_does_not_replace_running_loop():
    import asyncio

    startup_loop = asyncio.get_event_loop()
    running_at_start = asyncio.events._get_running_loop()

    assert running_at_start is startup_loop

    # (no await below: the try / finally keeps the loop of the test run in
    # place whatever happens)
    try:
        new_loop = asyncio.new_event_loop()
        running_after_new = asyncio.events._get_running_loop()

        assert new_loop is not startup_loop
        assert running_after_new is startup_loop
        assert asyncio.get_event_loop() is startup_loop

        new_loop.close()

        assert asyncio.events._get_running_loop() is startup_loop
        assert asyncio.get_event_loop() is startup_loop
    finally:
        asyncio.events._set_running_loop(startup_loop)
        asyncio.set_event_loop(startup_loop)


async def test_cancel_unhandled():
    import asyncio

    loop = asyncio.get_running_loop()

    async def f():
        await asyncio.sleep(1)

    # (pyodide reads the log of the page)
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        t = loop.create_task(f())
        print("done:", t.done())
        print("cancel:", t.cancel())
        # (pyodide: sleep(2)) until the task is cancelled, nobody awaits it
        for _ in range(1000):
            if t.done():
                break
            await asyncio.sleep(0)
        assert t.cancelled()
        del t
        gc.collect()
        await asyncio.sleep(0)

    assert "CancelledError" not in stderr.getvalue()


async def test_return_result():
    # test return result
    await run_with_resolve(
        """
        from js import resolve
        async def foo(arg):
            return arg

        def check_result(fut):
            result = fut.result()
            if result == 998:
                resolve()
            else:
                raise Exception(f"Unexpected result {result!r}")
        import asyncio
        fut = asyncio.ensure_future(foo(998))
        fut.add_done_callback(check_result)

        """,
    )


async def test_capture_exception():
    await run_with_resolve(
        """
        from unittest import TestCase
        raises = TestCase().assertRaises
        from js import resolve
        class MyException(Exception):
            pass
        async def foo(arg):
            raise MyException('oops')

        def capture_exception(fut):
            with raises(MyException):
                fut.result()
            resolve()
        import asyncio
        fut = asyncio.ensure_future(foo(998))
        fut.add_done_callback(capture_exception)
        """,
    )


async def test_await_js_promise():
    await run_with_resolve(
        f"""
        from js import fetch, resolve
        async def fetch_task():
            print('fetching data...')
            result = await fetch('{TEXT_URL}')
            resolve()
        import asyncio
        asyncio.ensure_future(fetch_task())
        None
        """,
    )


async def test_call_soon():
    await run_with_resolve(
        """
        from js import resolve
        def foo(arg):
            if arg == 'bar':
                resolve()
            else:
                raise Exception("Expected arg == 'bar'...")
        import asyncio
        asyncio.get_event_loop().call_soon(foo, 'bar')
        None
        """,
    )


async def test_contextvars():
    await run_with_resolve(
        """
        from js import resolve
        import contextvars
        request_id = contextvars.ContextVar('Id of request.')
        request_id.set(123)
        ctx = contextvars.copy_context()
        request_id.set(456)
        def func_ctx():
            if request_id.get() == 123:
                resolve()
            else:
                raise Exception(f"Expected request_id.get() == '123', got {request_id.get()!r}")
        import asyncio
        asyncio.get_event_loop().call_soon(func_ctx, context=ctx)
        None
        """,
    )


async def test_asyncio_exception():
    await run_with_resolve(
        """
        from unittest import TestCase
        raises = TestCase().assertRaises
        from js import resolve
        async def dummy_task():
            raise ValueError("oops!")
        async def capture_exception():
            with raises(ValueError):
                await dummy_task()
            resolve()
        import asyncio
        asyncio.ensure_future(capture_exception())
        None
        """,
    )


async def test_run_in_executor():
    # If run_in_executor tries to actually use ThreadPoolExecutor, it will throw
    # an error since we can't start threads
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    def f():
        return 5

    result = await asyncio.get_event_loop().run_in_executor(ThreadPoolExecutor(), f)
    assert result == 5


async def test_webloop_exception_handler():
    # (pyodide: xfail, "Works locally but failing in test suite as of #2022.")
    import asyncio

    async def test():
        raise Exception("test")

    # (pyodide reads the log of the page)
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        asyncio.ensure_future(test())
        # (pyodide: sleep(0.2)) the task ran and was released
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        gc.collect()
    assert "Task exception was never retrieved" in stderr.getvalue()

    loop = asyncio.get_event_loop()
    exc = []

    def exception_handler(loop, context):
        exc.append(context)

    loop.set_exception_handler(exception_handler)
    try:

        async def test():
            raise Exception("blah")

        asyncio.ensure_future(test())
        # (pyodide: sleep(100) in JS)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        gc.collect()
        assert exc[0]["exception"].args[0] == "blah"
    finally:
        loop.set_exception_handler(None)


@pytest.mark.xfail(reason="pyjs: no PyodideFuture (`then` / `catch` / `finally_` on futures)")
async def test_pyodide_future():
    import asyncio

    from pyodide.webloop import PyodideFuture

    fut: PyodideFuture[int]

    fut = PyodideFuture()
    increment = lambda x: x + 1
    tostring = repr

    def raises(x):
        raise Exception(x)

    rf = fut.then(increment).then(increment)
    fut.set_result(5)
    assert await rf == 7

    e = Exception("oops")
    fut = PyodideFuture()
    rf = fut.then(increment, tostring)
    fut.set_exception(e)
    assert await rf == repr(e)

    e = Exception("oops")
    fut = PyodideFuture()
    rf = fut.catch(tostring)
    fut.set_exception(e)
    assert await rf == repr(e)

    async def f(x):
        await asyncio.sleep(0.1)
        return x + 1

    fut = PyodideFuture()
    rf = fut.then(f)

    fut.set_result(6)
    assert await rf == 7

    fut = PyodideFuture()
    rf = fut.then(raises)
    fut.set_result(6)
    try:
        await rf
    except Exception:
        pass
    assert repr(rf.exception()) == repr(Exception(6))

    x = 0

    def incx():
        nonlocal x
        x += 1

    fut = PyodideFuture()
    rf = fut.then(increment).then(increment).finally_(incx).finally_(incx)
    assert x == 0
    fut.set_result(5)
    await rf
    assert x == 2

    fut = PyodideFuture()
    rf = fut.then(increment).then(increment).finally_(incx).finally_(incx)
    fut.set_exception(e)
    try:
        await rf
    except Exception:
        pass
    assert x == 4

    async def f1(x):
        if x == 0:
            return 7
        await asyncio.sleep(0.1)
        return f1(x - 1)

    fut = PyodideFuture()
    rf = fut.then(f1)
    fut.set_result(3)
    assert await rf == 7

    async def f2():
        await asyncio.sleep(0.1)
        raise e

    fut = PyodideFuture()
    rf = fut.finally_(f2)
    fut.set_result(3)
    try:
        await rf
    except Exception:
        pass
    assert rf.exception() == e

    fut = PyodideFuture()
    rf = fut.finally_(f2)
    fut.set_exception(Exception("oops!"))
    try:
        await rf
    except Exception:
        pass
    assert rf.exception() == e

    # Cancelling the source future must propagate to chained futures rather
    # than leaving them pending forever (gh-XXXX).
    fut = PyodideFuture()
    rf = fut.then(increment)
    fut.cancel()
    with pytest.raises(asyncio.CancelledError):
        await rf

    ran = 0

    def incran():
        nonlocal ran
        ran += 1

    fut = PyodideFuture()
    rf = fut.finally_(incran)
    fut.cancel()
    with pytest.raises(asyncio.CancelledError):
        await rf
    # finally_ still runs on cancellation, then propagates the cancellation.
    assert ran == 1


async def test_pyodide_future2():
    from js import fetch
    from pyodide.ffi import JSProxy

    # (pyodide: the type of `x` is JsFetchResponse)
    async def get_json(x) -> JSProxy:
        return await x.json()

    def get_name(x: JSProxy) -> str:
        return x[0]

    # pyodide fetches https://pypi.org/pypi/pytest/json and reads `info.name`;
    # here: a JSON file of the test driver, an array of the files of the suite
    url = "/tests/__files__.json"
    b = fetch(url).then(get_json)
    name = await asyncio.wait_for(b.then(get_name), 30)
    assert isinstance(name, str) and name


@pytest.mark.xfail(reason="pyjs: no PyodideTask (`then` / `catch` / `finally_` on tasks)")
async def test_pyodide_task():
    from asyncio import Future, ensure_future, sleep

    async def taskify(fut):
        return await fut

    def do_the_thing():
        d = dict(
            did_onresolve=None,
            did_onreject=None,
            did_onfinally=False,
        )
        f: Future[int] = Future()
        t = ensure_future(taskify(f))
        t.then(
            lambda v: d.update(did_onresolve=v), lambda e: d.update(did_onreject=e)
        ).finally_(lambda: d.update(did_onfinally=True))
        return f, d

    f, d = do_the_thing()
    f.set_result(7)
    await sleep(0.1)
    assert d == dict(
        did_onresolve=7,
        did_onreject=None,
        did_onfinally=True,
    )

    f, d = do_the_thing()
    e = Exception("Oops!")
    f.set_exception(e)
    assert d == dict(
        did_onresolve=None,
        did_onreject=None,
        did_onfinally=False,
    )
    await sleep(0.1)
    assert d == dict(
        did_onresolve=None,
        did_onreject=e,
        did_onfinally=True,
    )


@needs_zero_timeout
async def test_zero_timeout():
    import asyncio

    # pyodide: 1000 x sleep(0) take less than 4 s (1000 * 4 ms, the minimal
    # delay of nested setTimeout calls). Here: no setTimeout is used.
    with CountSetTimeout(asyncio.get_event_loop()) as counter:
        for _ in range(1000):
            await asyncio.sleep(0)

    assert counter.delays_ms == []


async def test_create_task_context():
    import asyncio as aio
    from contextvars import ContextVar, copy_context

    cvar = ContextVar("test_create_task_context", default=0)
    cvar.set(1)
    ctx_with_1 = copy_context()
    cvar.set(2)

    async def get_cvar() -> int:
        return cvar.get()

    assert await get_cvar() == 2  # Sanity check

    task = aio.create_task(get_cvar(), context=ctx_with_1)
    assert await task == 1


@pytest.mark.xfail(reason=NO_ASYNCGEN_TRACKING)
async def test_shutdown_closes_gens():
    """shutdown_asyncgens() closes all active async generators."""
    import asyncio

    loop = asyncio.get_running_loop()

    closed = set()

    async def ag(name):
        try:
            yield name
        finally:
            closed.add(name)

    g1 = ag("g1")
    g2 = ag("g2")
    assert await g1.__anext__() == "g1"
    assert await g2.__anext__() == "g2"
    assert closed == set()

    await loop.shutdown_asyncgens()
    assert closed == {"g1", "g2"}


@pytest.mark.xfail(reason=NO_ASYNCGEN_TRACKING)
async def test_shutdown_idempotent():
    """Multiple shutdown_asyncgens() calls are safe and do nothing after first call."""
    import asyncio

    loop = asyncio.get_running_loop()

    closed = []

    async def ag(name):
        try:
            yield name
        finally:
            closed.append(name)

    g = ag("g")
    assert await g.__anext__() == "g"

    await loop.shutdown_asyncgens()
    assert closed == ["g"]

    await loop.shutdown_asyncgens()
    assert closed == ["g"]


@pytest.mark.xfail(reason=NO_ASYNCGEN_TRACKING)
async def test_shutdown_with_cancelled_tasks():
    """Async generators in cancelled tasks are finalized by shutdown_asyncgens."""
    import asyncio

    loop = asyncio.get_running_loop()

    finalized_gens = set()

    async def ag(name):
        try:
            await asyncio.sleep(10)
            yield
        finally:
            finalized_gens.add(name)

    async def run_ag(name):
        async for _ in ag(name):
            pass

    task1 = loop.create_task(run_ag("g1"))
    task2 = loop.create_task(run_ag("g2"))

    await asyncio.sleep(0)

    task1.cancel()
    task2.cancel()

    assert finalized_gens == set(), "Generator was finalized prematurely."

    await loop.shutdown_asyncgens()

    assert finalized_gens == {"g1", "g2"}, (
        "Not all generators in cancelled tasks were finalized."
    )


@pytest.mark.xfail(
    reason="pyjs: no async generator tracking by the WebLoop: no ResourceWarning for an async "
    "generator started after shutdown_asyncgens()"
)
async def test_warning_after_shutdown():
    """Creating generators after shutdown emits ResourceWarning."""
    import asyncio
    import warnings

    loop = asyncio.get_running_loop()

    await loop.shutdown_asyncgens()

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always", ResourceWarning)

        async def ag():
            yield 1

        g = ag()
        await g.__anext__()
        await g.aclose()

    assert any(issubclass(warn.category, ResourceWarning) for warn in w)


async def test_create_task_with_task_factory():
    import asyncio

    loop = asyncio.get_event_loop()
    calls = []

    def factory(loop, coro, **kwargs):
        calls.append(kwargs)
        return asyncio.Task(coro, loop=loop, **kwargs)

    async def f():
        return 7

    loop.set_task_factory(factory)
    try:
        task = loop.create_task(f(), name="my task")
        assert await task == 7
        assert task.get_name() == "my task"
        assert calls == [{"name": "my task"}]
    finally:
        loop.set_task_factory(None)


async def test_eager_task_factory():
    import asyncio

    loop = asyncio.get_event_loop()
    started = []

    async def f():
        started.append(True)
        return 7

    loop.set_task_factory(asyncio.eager_task_factory)
    try:
        task = loop.create_task(f(), name="eager")
        # An eager task starts running in create_task
        assert started == [True]
        assert await task == 7
        assert task.get_name() == "eager"
    finally:
        loop.set_task_factory(None)


async def test_create_task_eager_start():
    import asyncio

    loop = asyncio.get_event_loop()
    started = []

    async def f():
        started.append(True)
        return 7

    task = loop.create_task(f(), eager_start=True)
    # An eager task starts running in create_task
    assert started == [True]
    assert await task == 7


# ---------------------------------------------------------------------------
# src/tests/test_webloop_webworker.py
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not IN_WORKER, reason="a test for web workers")
async def test_webworker_zero_timeout1():
    output = await run_js_async(
        "return await pyjs.runPythonAsync("
        + json.dumps(
            """
            import asyncio
            await asyncio.sleep(0)
            42
            """
        )
        + ");"
    )
    assert output == 42


@needs_zero_timeout
@pytest.mark.skipif(not IN_WORKER, reason="a test for web workers")
async def test_webworker_zero_timeout2():
    # the python code of pyodide's test, with the two changes of
    # test_zero_timeout (no timing) and of the name of the worker flag
    globals()["CountSetTimeout"] = CountSetTimeout
    output = await run_js_async(
        "return await pyjs.runPythonAsync("
        + json.dumps(
            """
            import asyncio
            import sys

            import pyjs

            assert pyjs._module._IS_BROWSER_WORKER_THREAD is True

            CountSetTimeout = sys.modules["%s"].CountSetTimeout
            with CountSetTimeout(asyncio.get_event_loop()) as counter:
                for _ in range(1000):
                    await asyncio.sleep(0)

            assert counter.delays_ms == []

            42
            """
            % __name__
        )
        + ");"
    )

    assert output == 42
