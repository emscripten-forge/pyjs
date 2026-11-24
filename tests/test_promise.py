"""Async tests for awaiting JS promises from python: results and especially
rejections.

A rejected promise raises a JSException, like a synchronous `throw` of the
same value does (pyodide compatible); it is also a RuntimeError.
"""

import asyncio

import pyjs
from pyjs import js


def _rejected(js_expr):
    """A promise rejected with the value of the JS expression `js_expr`."""
    return js.Function(f"return Promise.reject({js_expr});")()


async def _await_exception(promise):
    """the exception awaiting `promise` raises"""
    try:
        await promise
    except BaseException as e:
        return e
    raise AssertionError("expected the promise to be rejected")


def _sync_exception(js_expr):
    """the exception a synchronous `throw` of the JS expression raises"""
    try:
        js.Function(f"throw {js_expr};")()
    except BaseException as e:
        return e
    raise AssertionError("expected an exception")


async def test_promise_resolved_values():
    assert await js.Promise.resolve(42) == 42
    assert await js.Promise.resolve("text") == "text"
    assert await js.Promise.resolve(None) is None
    assert await js.Function("return Promise.resolve(null)")() is pyjs.jsnull
    assert pyjs.to_py(await js.Function("return Promise.resolve([1, 2, 3])")()) == [1, 2, 3]


async def test_promise_rejected_error_names():
    for js_cls in ["Error", "TypeError", "RangeError", "SyntaxError", "ReferenceError", "URIError"]:
        e = await _await_exception(_rejected(f"new {js_cls}('msg-{js_cls}')"))
        assert type(e) is pyjs.JSException, (js_cls, type(e))
        assert e.name == js_cls, (js_cls, e.name)
        assert e.message == f"msg-{js_cls}", (js_cls, e.message)
        assert f"msg-{js_cls}" in str(e), (js_cls, str(e))


async def test_promise_rejection_same_as_sync_throw():
    for js_expr in [
        "new Error('a')",
        "new TypeError('b')",
        "new RangeError('c')",
        "new DOMException('d', 'AbortError')",
        "{code: 42}",
    ]:
        sync_exc = _sync_exception(js_expr)
        async_exc = await _await_exception(_rejected(js_expr))
        assert type(sync_exc) is pyjs.JSException, (js_expr, type(sync_exc))
        assert type(async_exc) is pyjs.JSException, (js_expr, type(async_exc))
        assert async_exc.name == sync_exc.name, (js_expr, sync_exc.name, async_exc.name)
        assert async_exc.message == sync_exc.message, (js_expr, sync_exc.message, async_exc.message)


async def test_promise_rejection_is_runtime_error():
    # awaiting a rejected promise used to raise a plain RuntimeError
    for js_expr in ["new Error('x')", "'text'", "undefined", "null", "{a: 1}"]:
        try:
            await _rejected(js_expr)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"expected a RuntimeError for {js_expr}")


async def test_promise_rejection_custom_error_subclass():
    p = js.Function(
        """
        class MyError extends Error {
            constructor(message) { super(message); this.name = "MyError"; this.extra = 7; }
        }
        return Promise.reject(new MyError("custom"));
        """
    )()
    e = await _await_exception(p)
    assert isinstance(e, pyjs.JSException)
    assert e.name == "MyError", e.name
    assert "custom" in str(e)
    assert e.js_error.extra == 7


async def test_promise_rejection_keeps_the_js_error_object():
    err = js.Function("const e = new TypeError('the one'); globalThis.__pyjs_test_err = e; return e;")()
    try:
        e = await _await_exception(js.Promise.reject(err))
        is_same = js.Function("a", "return a === globalThis.__pyjs_test_err;")
        assert is_same(e.js_error)
        assert e.js_error == err
        assert e.js_error.message == "the one"
    finally:
        js.Function("delete globalThis.__pyjs_test_err;")()


async def test_promise_rejection_non_error_values():
    for js_expr, text, value in [
        ("'just a string'", "just a string", "just a string"),
        ("undefined", "None", None),
        ("null", "jsnull", pyjs.jsnull),
        ("42", "42", 42),
        ("true", "True", True),
    ]:
        e = await _await_exception(_rejected(js_expr))
        assert isinstance(e, pyjs.JSException), (js_expr, type(e))
        assert text in str(e), (js_expr, str(e))
        assert e.js_error is value or e.js_error == value, (js_expr, e.js_error)


async def test_promise_rejection_plain_object():
    e = await _await_exception(_rejected("{code: 42, reason: 'nope'}"))
    assert isinstance(e, pyjs.JSException), type(e)
    assert "42" in str(e) and "nope" in str(e), str(e)
    assert e.js_error.code == 42


async def test_promise_async_function_throw():
    p = js.Function(
        "return (async () => { await null; throw new RangeError('from async'); })();"
    )()
    e = await _await_exception(p)
    assert e.name == "RangeError", e.name
    assert "from async" in str(e)


async def test_promise_delayed_rejection():
    p = js.Function(
        "return new Promise((_, reject) => setTimeout(() => reject(new Error('later')), 20));"
    )()
    e = await _await_exception(p)
    assert e.name == "Error", e.name
    assert "later" in str(e)


async def test_promise_rejection_in_gather():
    ok = js.Promise.resolve(1)
    bad = _rejected("new TypeError('in gather')")
    try:
        await asyncio.gather(ok, bad)
    except pyjs.JSException as e:
        assert e.name == "TypeError", e.name
        assert "in gather" in str(e)
    else:
        raise AssertionError("expected a JSException")

    results = await asyncio.gather(
        js.Promise.resolve(1), _rejected("new Error('kept')"), return_exceptions=True
    )
    assert results[0] == 1
    assert isinstance(results[1], pyjs.JSException) and "kept" in str(results[1])


async def test_promise_wait_for_timeout():
    never = js.Function("return new Promise(() => {});")()
    try:
        await asyncio.wait_for(never, 0.05)
    except (asyncio.TimeoutError, TimeoutError):
        pass
    else:
        raise AssertionError("expected a timeout")


async def test_promise_many_rejections():
    # every rejection is delivered once, to the right awaiter
    promises = [_rejected(f"new Error('n{i}')") for i in range(50)]
    results = await asyncio.gather(*promises, return_exceptions=True)
    for i, e in enumerate(results):
        assert isinstance(e, pyjs.JSException), (i, type(e))
        assert e.message == f"n{i}", (i, e.message)


async def test_js_awaits_failing_python_coroutine():
    # python -> JS: JS awaits a python coroutine that raises
    async def fails():
        await asyncio.sleep(0)
        raise ValueError("python side")

    js_catch = js.Function(
        "p",
        "return p.then(() => 'resolved', (err) => 'rejected: ' + String(err));",
    )
    result = await js_catch(fails())
    assert result.startswith("rejected"), result
    assert "python side" in result, result


async def test_js_awaits_python_coroutine_result():
    # python -> JS: the result of a coroutine, also a python object, arrives
    async def works():
        await asyncio.sleep(0)
        return {"answer": 42}

    js_then = js.Function("p", "return p.then((result) => result.get('answer'));")
    assert await js_then(works()) == 42


async def test_run_sync_rejections():
    # with JSPI, run_sync raises like await
    if not pyjs.can_run_sync():
        return
    for js_expr, name in [
        ("new TypeError('sync t')", "TypeError"),
        ("new Error('sync e')", "Error"),
        ("new DOMException('sync x', 'AbortError')", "AbortError"),
    ]:
        try:
            pyjs.run_sync(_rejected(js_expr))
        except pyjs.JSException as e:
            assert e.name == name, (js_expr, e.name)
            assert "sync" in str(e)
        else:
            raise AssertionError(f"expected a JSException for {js_expr}")


async def test_promise_rejection_is_not_unhandled():
    # a rejected promise awaited from python is handled: pyjs must not create a
    # derived promise whose rejection nobody handles (unhandledrejection event)
    counter = js.Function(
        """
        const counter = { n: 0 };
        counter.listener = () => { counter.n += 1; };
        globalThis.addEventListener("unhandledrejection", counter.listener);
        return counter;
        """
    )()
    try:
        await _await_exception(_rejected("new Error('handled')"))
        # unhandled rejections are reported at the end of the task they happen
        # in: two later tasks (order, not time) are after any report
        next_task = js.Function("return new Promise((resolve) => setTimeout(resolve, 0));")
        await next_task()
        await next_task()
        assert counter.n == 0, f"{counter.n} unhandled rejection(s)"
    finally:
        js.globalThis.removeEventListener("unhandledrejection", counter.listener)
