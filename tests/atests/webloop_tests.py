"""Async tests for pyjs.WebLoop scheduling (call_soon / call_later / awaiting JS).

These run in the browser main thread *and* in a worker (see build_local.sh --test).
"""

import asyncio
import contextvars
import time

import pyjs
from pyjs import js


def _loop():
    return asyncio.get_running_loop()


async def _drain(n=3):
    # give already scheduled callbacks a chance to run
    for _ in range(n):
        await asyncio.sleep(0)


async def _wait_for(predicate, timeout=2.0):
    t0 = time.monotonic()
    while not predicate():
        if time.monotonic() - t0 > timeout:
            raise TimeoutError("condition not reached in time")
        await asyncio.sleep(0)


async def _check_call_soon_fifo():
    order = []
    for i in range(100):
        _loop().call_soon(order.append, i)
    await _wait_for(lambda: len(order) == 100)
    assert order == list(range(100))


async def _check_sleep0_many():
    for _ in range(50):
        await asyncio.sleep(0)


# -- call_soon ---------------------------------------------------------------


async def test_webloop_call_soon_fifo():
    await _check_call_soon_fifo()


async def test_webloop_call_soon_args():
    got = []
    _loop().call_soon(lambda *a: got.append(a), 1, "two", None)
    await _wait_for(lambda: got)
    assert got == [(1, "two", None)]


async def test_webloop_call_soon_returns_handle():
    h = _loop().call_soon(lambda: None)
    assert isinstance(h, asyncio.Handle)
    await _drain()


async def test_webloop_call_soon_cancel():
    called = []
    h = _loop().call_soon(called.append, "cancelled")
    _loop().call_soon(called.append, "kept")
    h.cancel()
    assert h.cancelled()
    await _wait_for(lambda: called)
    await _drain()
    assert called == ["kept"]


async def test_webloop_call_soon_contextvars():
    var = contextvars.ContextVar("var", default="default")
    got = []

    ctx = contextvars.copy_context()
    ctx.run(var.set, "in_ctx")

    _loop().call_soon(lambda: got.append(var.get()), context=ctx)
    _loop().call_soon(lambda: got.append(var.get()))
    await _wait_for(lambda: len(got) == 2)
    assert got == ["in_ctx", "default"]


async def test_webloop_call_soon_nested_runs_after_queued():
    order = []

    def outer():
        order.append("outer")
        _loop().call_soon(order.append, "nested")

    _loop().call_soon(outer)
    _loop().call_soon(order.append, "second")
    await _wait_for(lambda: len(order) == 3)
    assert order == ["outer", "second", "nested"]


async def test_webloop_call_soon_threadsafe():
    got = []
    _loop().call_soon_threadsafe(got.append, 42)
    await _wait_for(lambda: got)
    assert got == [42]


async def test_webloop_call_soon_exception_goes_to_handler():
    loop = _loop()
    contexts = []
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda loop, context: contexts.append(context))
    try:
        after = []

        def boom():
            raise ValueError("boom")

        loop.call_soon(boom)
        loop.call_soon(after.append, "still running")
        await _wait_for(lambda: after)
        await _drain()
    finally:
        loop.set_exception_handler(old_handler)

    assert after == ["still running"]
    assert len(contexts) == 1
    assert isinstance(contexts[0]["exception"], ValueError)


async def test_webloop_call_soon_before_call_later():
    loop = _loop()
    if loop._macrotask_queue is None:
        # setTimeout fallback (Safari): call_soon is setTimeout(0), which is
        # clamped to >= 4ms when nested, so the browser may run the earlier
        # scheduled 5ms timer first. The ordering is only guaranteed on the
        # fast path.
        return
    order = []
    loop.call_later(0.005, order.append, "later")
    for i in range(5):
        loop.call_soon(order.append, i)
    await _wait_for(lambda: len(order) == 6)
    assert order == [0, 1, 2, 3, 4, "later"], order


async def test_webloop_call_soon_many():
    n = 10_000
    got = []
    for i in range(n):
        _loop().call_soon(got.append, i)
    await _wait_for(lambda: len(got) == n, timeout=10.0)
    assert got == list(range(n))


# -- call_later --------------------------------------------------------------


async def test_webloop_call_later_delay():
    loop = _loop()
    t0 = loop.time()
    fired = []
    loop.call_later(0.05, lambda: fired.append(loop.time()))
    await _wait_for(lambda: fired)
    assert fired[0] - t0 >= 0.045


async def test_webloop_call_later_order():
    order = []
    loop = _loop()
    loop.call_later(0.03, order.append, 3)
    loop.call_later(0.01, order.append, 1)
    loop.call_later(0.02, order.append, 2)
    await _wait_for(lambda: len(order) == 3)
    assert order == [1, 2, 3]


async def test_webloop_call_later_cancel():
    called = []
    h = _loop().call_later(0.01, called.append, 1)
    h.cancel()
    await asyncio.sleep(0.03)
    assert called == []


# -- tasks / sleep -------------------------------------------------------------


async def test_webloop_sleep0():
    await _check_sleep0_many()


async def test_webloop_sleep0_is_fast():
    # with setTimeout(0) every hop is clamped to >= 4ms by the browser
    if _loop()._macrotask_queue is None:
        return  # environment without fast path (e.g. Safari)
    n = 200
    t0 = time.perf_counter()
    for _ in range(n):
        await asyncio.sleep(0)
    per_hop = (time.perf_counter() - t0) / n
    assert per_hop < 0.001, f"asyncio.sleep(0) took {per_hop * 1000:.3f}ms per call"


async def test_webloop_sleep_positive():
    t0 = time.perf_counter()
    await asyncio.sleep(0.02)
    assert time.perf_counter() - t0 >= 0.015


async def test_webloop_tasks_interleave():
    order = []

    async def worker(name):
        for _ in range(5):
            order.append(name)
            await asyncio.sleep(0)

    await asyncio.gather(worker("a"), worker("b"))
    assert order == ["a", "b"] * 5


async def test_webloop_gather_many_sleep0():
    results = await asyncio.gather(*[asyncio.sleep(0, result=i) for i in range(1000)])
    assert results == list(range(1000))


async def test_webloop_create_task_result():
    async def f(x):
        await asyncio.sleep(0)
        return x * 2

    assert await asyncio.create_task(f(21)) == 42


async def test_webloop_task_exception():
    async def f():
        await asyncio.sleep(0)
        raise KeyError("k")

    task = asyncio.create_task(f())
    try:
        await task
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")


async def test_webloop_task_cancel():
    started = asyncio.Event()

    async def forever():
        started.set()
        while True:
            await asyncio.sleep(0)

    task = asyncio.create_task(forever())
    await started.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert task.cancelled()


async def test_webloop_wait_for_timeout():
    try:
        await asyncio.wait_for(asyncio.sleep(1.0), timeout=0.02)
    except asyncio.TimeoutError:
        pass
    else:
        raise AssertionError("expected TimeoutError")


async def test_webloop_future_set_result_via_call_soon():
    loop = _loop()
    fut = loop.create_future()
    loop.call_soon(fut.set_result, "done")
    assert await fut == "done"


async def test_webloop_event_and_queue():
    q = asyncio.Queue()

    async def producer():
        for i in range(20):
            await q.put(i)
            await asyncio.sleep(0)

    async def consumer():
        return [await q.get() for _ in range(20)]

    _, got = await asyncio.gather(producer(), consumer())
    assert got == list(range(20))


# -- interaction with the browser / JS event loop ------------------------------


async def test_webloop_does_not_starve_js_timers():
    # a busy python loop of sleep(0) must still let JS setTimeout callbacks run
    state = js.Function("return {fired: false}")()
    js.Function("s", "setTimeout(() => { s.fired = true; }, 0)")(state)
    await _wait_for(lambda: pyjs.to_py(state.fired))


async def test_webloop_does_not_starve_js_promises():
    state = js.Function("return {fired: false}")()
    js.Function("s", "Promise.resolve().then(() => { s.fired = true; })")(state)
    await _wait_for(lambda: pyjs.to_py(state.fired))


async def test_webloop_await_js_resolved_promise():
    assert await js.Function("return Promise.resolve(7)")() == 7


async def test_webloop_await_js_settimeout_promise():
    p = js.Function("return new Promise(r => setTimeout(() => r('t'), 5))")()
    assert await p == "t"


async def test_webloop_await_js_microtask_promise():
    p = js.Function("return new Promise(r => queueMicrotask(() => r('m')))")()
    assert await p == "m"


async def test_webloop_await_js_rejected_promise():
    p = js.Function("return Promise.reject(new Error('nope'))")()
    try:
        await p
    except pyjs.JsError as e:
        # a JsException (pyodide compatible), still a RuntimeError (as before)
        assert isinstance(e, pyjs.JsException) and isinstance(e, RuntimeError)
        assert e.name == "Error"
        assert "nope" in str(e)
    else:
        raise AssertionError("expected an exception")


async def test_webloop_await_js_rejected_promise_abort_error():
    # what fetch / stream reads reject with when an AbortController aborts
    # (httpx2-jsfetch turns it into a timeout via its `name`)
    p = js.Function("return Promise.reject(new DOMException('aborted', 'AbortError'))")()
    try:
        await p
    except pyjs.JsException as e:
        assert e.name == "AbortError", e.name
    else:
        raise AssertionError("expected an exception")


async def test_webloop_await_js_rejected_promise_non_error_values():
    for js_code, text in [
        ("return Promise.reject('just a string')", "just a string"),
        ("return Promise.reject(undefined)", "None"),
        ("return Promise.reject(42)", "42"),
    ]:
        try:
            await js.Function(js_code)()
        except pyjs.JsException as e:
            assert text in str(e), (js_code, str(e))
        else:
            raise AssertionError(f"expected an exception for {js_code}")


async def test_webloop_js_awaits_python_coroutine_result():
    # python -> JS promise -> awaited in JS -> back in python
    async def compute():
        await asyncio.sleep(0)
        return 5

    def executor(resolve, reject):
        async def run():
            resolve(await compute())

        asyncio.ensure_future(run())

    p = pyjs.promise(executor)
    add_one = js.Function("p", "return p.then(x => x + 1)")
    assert await add_one(p) == 6


# -- fallback path / encapsulation ---------------------------------------------


async def test_webloop_fallback_without_fast_path():
    # the loop must also work when only setTimeout is available
    loop = _loop()
    saved = loop._macrotask_queue
    loop._macrotask_queue = None
    try:
        await _check_call_soon_fifo()
        await _check_sleep0_many()
    finally:
        loop._macrotask_queue = saved
    await _check_call_soon_fifo()


async def test_webloop_scheduler_is_not_exposed():
    names = [n.lower() for n in dir(pyjs)]
    assert not any("macrotask" in n or "messagechannel" in n for n in names)

    global_keys = pyjs.to_py(js.Function("return Object.keys(globalThis)")())
    assert not any(
        "macrotask" in k.lower() or "channel" in k.lower() for k in global_keys
    )
