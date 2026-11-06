"""Async tests for awaiting JS promises from python: results and especially
rejections (include/pyjs/pre_js/promise.js, module/pyjs/extend_js_val.py).

A rejected promise raises the same JsException subclass as a synchronous
`throw` of the same value (pyodide compatible), which is also a RuntimeError.
"""

import asyncio

import pyjs
from pyjs import js


def _rejected(js_expr):
    """A promise rejected with the value of the JS expression `js_expr`."""
    return js.Function(f"return Promise.reject({js_expr});")()


async def _await_exception(promise):
    try:
        await promise
    except BaseException as e:
        return e
    raise AssertionError("expected the promise to be rejected")


def _sync_exception(js_expr):
    try:
        js.Function(f"throw {js_expr};")()
    except BaseException as e:
        return e
    raise AssertionError("expected an exception")


async def test_promise_resolved_values():
    assert await js.Promise.resolve(42) == 42
    assert await js.Promise.resolve("text") == "text"
    assert await js.Promise.resolve(None) is None
    assert await js.Function("return Promise.resolve([1, 2, 3])")() is not None


async def test_promise_rejected_error_classes():
    for js_cls, py_cls in [
        ("Error", pyjs.JsError),
        ("TypeError", pyjs.JsTypeError),
        ("RangeError", pyjs.JsRangeError),
        ("SyntaxError", pyjs.JsSyntaxError),
        ("ReferenceError", pyjs.JsReferenceError),
        ("URIError", pyjs.JsURIError),
    ]:
        e = await _await_exception(_rejected(f"new {js_cls}('msg-{js_cls}')"))
        assert type(e) is py_cls, (js_cls, type(e))
        assert e.name == js_cls, (js_cls, e.name)
        assert f"msg-{js_cls}" in str(e), (js_cls, str(e))


async def test_promise_rejection_same_class_as_sync_throw():
    for js_expr in [
        "new Error('a')",
        "new TypeError('b')",
        "new RangeError('c')",
        "new DOMException('d', 'AbortError')",
        "'just a string'",
        "{code: 42}",
    ]:
        sync_exc = _sync_exception(js_expr)
        async_exc = await _await_exception(_rejected(js_expr))
        assert isinstance(sync_exc, pyjs.JsException), (js_expr, type(sync_exc))
        assert isinstance(async_exc, pyjs.JsException), (js_expr, type(async_exc))
        if isinstance(sync_exc, pyjs.JsError) or js_expr.startswith("new Error"):
            assert type(async_exc) is type(sync_exc), (js_expr, type(sync_exc), type(async_exc))


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
    assert isinstance(e, pyjs.JsException)
    assert e.name == "MyError", e.name
    assert "custom" in str(e)
    assert e.get_js_proxy().extra == 7


async def test_promise_rejection_keeps_the_js_error_object():
    err = js.Function("const e = new TypeError('the one'); globalThis.__pyjs_test_err = e; return e;")()
    try:
        e = await _await_exception(js.Promise.reject(err))
        is_same = js.Function("a", "return a === globalThis.__pyjs_test_err;")
        assert is_same(e.get_js_proxy())
        assert e.get_js_proxy().message == "the one"
    finally:
        js.Function("delete globalThis.__pyjs_test_err;")()


async def test_promise_rejection_non_error_values():
    for js_expr, text in [
        ("'just a string'", "just a string"),
        ("undefined", "None"),
        ("null", "None"),
        ("42", "42"),
        ("true", "True"),
    ]:
        e = await _await_exception(_rejected(js_expr))
        assert isinstance(e, pyjs.JsException), (js_expr, type(e))
        assert text in str(e), (js_expr, str(e))


async def test_promise_rejection_plain_object():
    e = await _await_exception(_rejected("{code: 42, reason: 'nope'}"))
    assert isinstance(e, pyjs.JsException), type(e)
    assert "42" in str(e) and "nope" in str(e), str(e)
    assert e.get_js_proxy().code == 42


async def test_promise_async_function_throw():
    p = js.Function(
        "return (async () => { await null; throw new RangeError('from async'); })();"
    )()
    e = await _await_exception(p)
    assert type(e) is pyjs.JsRangeError, type(e)
    assert "from async" in str(e)


async def test_promise_delayed_rejection():
    p = js.Function(
        "return new Promise((_, reject) => setTimeout(() => reject(new Error('later')), 20));"
    )()
    e = await _await_exception(p)
    assert type(e) is pyjs.JsError, type(e)
    assert "later" in str(e)


async def test_promise_rejection_in_gather():
    ok = js.Promise.resolve(1)
    bad = _rejected("new TypeError('in gather')")
    try:
        await asyncio.gather(ok, bad)
    except pyjs.JsTypeError as e:
        assert "in gather" in str(e)
    else:
        raise AssertionError("expected JsTypeError")

    results = await asyncio.gather(
        js.Promise.resolve(1), _rejected("new Error('kept')"), return_exceptions=True
    )
    assert results[0] == 1
    assert isinstance(results[1], pyjs.JsError) and "kept" in str(results[1])


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
        assert isinstance(e, pyjs.JsError), (i, type(e))
        assert f"n{i}" in str(e), (i, str(e))


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


async def test_run_sync_rejection_classes():
    # with JSPI, run_sync raises the same classes as await
    if not pyjs.can_run_sync():
        return
    for js_expr, py_cls in [
        ("new TypeError('sync t')", pyjs.JsTypeError),
        ("new Error('sync e')", pyjs.JsError),
    ]:
        try:
            pyjs.run_sync(_rejected(js_expr))
        except py_cls as e:
            assert "sync" in str(e)
        else:
            raise AssertionError(f"expected {py_cls.__name__}")
    try:
        pyjs.run_sync(_rejected("new DOMException('x', 'AbortError')"))
    except pyjs.JsException as e:
        assert e.name == "AbortError", e.name
    else:
        raise AssertionError("expected JsException")
