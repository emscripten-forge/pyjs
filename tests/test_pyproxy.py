"""PyProxy (a Python object in JavaScript, src/js/pyproxy.ts): who owns which
reference, and when it is given back.

These tests look at the Python side of a PyProxy operation: reference counts
and object lifetimes. A PyProxy that releases its object too early is a
use-after-free, one that never releases it a leak; neither shows in the
result of the operation itself.
"""

import asyncio
import sys

import pytest

import pyjs
from helpers import require_js_gc
from pyjs.code import run_js


def test_in_operator_does_not_leak():
    """`"name" in proxy` (JavaScript) looks the attribute up in Python. The
    value that lookup produces (here a new bound method each time, which
    refers to `obj`) must be released again."""

    class Obj:
        def method(self):
            pass

    obj = Obj()
    count = run_js(
        """
        (proxy, n) => {
            let found = 0;
            for (let i = 0; i < n; i++) {
                if ("method" in proxy) found += 1;
            }
            return found;
        }
        """
    )
    before = sys.getrefcount(obj)
    assert count(obj, 100) == 100
    assert sys.getrefcount(obj) == before


async def test_iterator_lives_as_long_as_the_for_of_loop():
    """`for (const x of proxy)` holds a Python iterator for the whole loop.

    JavaScript's garbage collector must not release it in the middle (the
    loop gives it every chance: gc() + a turn of the event loop per step),
    and it is released exactly once, when the loop ends."""
    require_js_gc()
    deleted = []

    class Iterator:
        def __init__(self):
            self.i = 0

        def __iter__(self):
            return self

        def __next__(self):
            self.i += 1
            if self.i > 5:
                raise StopIteration
            return self.i

        def __del__(self):
            deleted.append(self.i)

    class Iterable:
        def __iter__(self):
            return Iterator()

    loop = run_js(
        """
        async (iterable, deletedSoFar) => {
            const turn = () => new Promise((resolve) => setTimeout(resolve, 0));
            const seen = [];
            for (const x of iterable) {
                // (finalizers of collected objects run in a later turn)
                gc();
                await turn();
                gc();
                await turn();
                seen.push([x, deletedSoFar()]);
            }
            return seen;
        }
        """
    )
    seen = (await loop(Iterable(), lambda: len(deleted))).to_py()
    # every step ran, and the iterator was alive at each of them
    assert seen == [[1, 0], [2, 0], [3, 0], [4, 0], [5, 0]], seen
    # released when the loop ended (after the StopIteration: i is 6), once
    assert deleted == [6], deleted


async def test_js_function_returning_its_coroutine_argument():
    """A coroutine passed through a JavaScript function comes back untouched:
    pyjs must not start it behind the caller's back (it used to, by calling
    `then` on the returned value)."""

    async def coroutine():
        await asyncio.sleep(0)
        return 7

    identity = run_js("(x) => x")
    c = coroutine()
    assert identity(c) is c
    assert await c == 7


def test_js_function_returning_a_lazy_thenable_is_not_started():
    """A "lazy thenable" (an object that only starts working when its `then`
    is called, like the query builders of database libraries) returned from
    a call with a Python object as argument: pyjs must not call its `then`."""
    make = run_js(
        """
        (pyObject) => ({
            started: 0,
            then(resolve) { this.started += 1; resolve(1); },
        })
        """
    )
    thenable = make([1, 2, 3])
    assert thenable.started == 0


def test_new_on_a_class_proxy_creates_an_instance():
    """`new proxy(...)` in JavaScript, where the proxy is a Python class:
    creates an instance, like calling it (it used to return an empty
    JavaScript object without calling Python at all)."""

    class Point:
        def __init__(self, x):
            self.x = x

    x_of_new = run_js("(Class) => { const p = new Class(3); return p.x; }")
    assert x_of_new(Point) == 3


def test_own_keys_do_not_show_internals():
    """The object behind a PyProxy carries the proxy's internal state. It
    must not show up as a property of the proxy (in Object.keys, JSON, a
    spread), where it would also be looked up as a Python attribute."""

    class Obj:
        state = "a Python attribute called state"

    keys = run_js("(p) => Object.keys(p).join(',')")
    assert keys(Obj()) == ""
    assert keys(len) == ""
    spread = run_js("(p) => Object.keys({...p}).join(',')")
    assert spread(Obj()) == ""


def test_failing_argument_conversion_leaks_no_handles():
    """A call into Python whose LAST argument cannot be converted (a
    destroyed proxy): what was already written for the arguments before it
    (handles of JavaScript objects) is given back."""
    from helpers import handle_count

    dead = pyjs.create_proxy([])
    dead.destroy()
    call = run_js(
        """
        (f, dead) => {
            for (let i = 0; i < 20; i++) {
                try {
                    f({}, [], dead);
                } catch (error) {
                    // expected: the proxy is destroyed
                }
            }
        }
        """
    )
    before = handle_count()
    call(lambda *args: None, dead)
    assert handle_count() == before


def test_python_error_made_by_user_code():
    """`new pyjs.PythonError(...)` in user code (the class is public, for
    `instanceof`): such an error stands for no Python exception. Thrown into
    Python it is an ordinary JavaScript error, not a crash."""
    throw = run_js("() => { throw new pyjs.PythonError('ValueError', 'made in JavaScript'); }")
    with pytest.raises(pyjs.JSException, match="made in JavaScript"):
        throw()
    # and Python still works
    assert run_js("(f) => f(20)")(lambda x: x + 1) == 21


def test_error_whose_text_calls_into_javascript():
    """A Python exception on its way to JavaScript is formatted (its
    `__str__` runs). If that calls JavaScript, which calls Python, which
    raises again, the inner error must not replace the outer one."""
    swallow = run_js("(f) => { try { f(); } catch (error) { return 'caught'; } }")

    def fails():
        raise ZeroDivisionError("the inner error")

    class Outer(Exception):
        def __str__(self):
            assert swallow(fails) == "caught"
            return "the outer error"

    def raises_outer():
        raise Outer()

    # (through JavaScript and back: the exception Python gets is the one
    # JavaScript was told about)
    call = run_js("(f) => f()")
    with pytest.raises(Outer):
        call(raises_outer)


def test_keyword_argument_called_proto():
    """keyword arguments arrive in JavaScript as one object; a keyword
    called `__proto__` is a property of it like any other"""
    names = run_js("(options) => Object.getOwnPropertyNames(options).sort().join(',')")
    assert names(**{"__proto__": 1, "a": 2}) == "__proto__,a"


def test_int_subclass_with_its_own_str():
    """An int that does not fit a JavaScript number goes over as BigInt, via
    its digits. A subclass with its own `__str__` (an Enum with int values)
    must still send the digits."""
    import enum

    class Big(int, enum.Enum):
        A = 2**70

    describe = run_js("(x) => typeof x + ' ' + String(x)")
    assert describe(Big.A) == f"bigint {2**70}"


@pytest.mark.skipif(not pyjs.jspi_enabled(), reason="needs JSPI")
async def test_call_promising_keeps_its_arguments():
    """`f.callPromising(x)` called by JavaScript that Python called: the
    call starts later (after the current Python code is done), when `x`, an
    argument of the outer call, would normally be gone already."""
    start = run_js("(f, x) => { globalThis.__pending = f.callPromising(x); }")
    data = [1, 2, 3]
    try:
        start(pyjs.create_proxy(lambda value: sum(value)), data)
        assert await run_js("globalThis.__pending") == 6
    finally:
        run_js("delete globalThis.__pending")


@pytest.mark.skipif(not pyjs.jspi_enabled(), reason="needs JSPI")
async def test_run_sync_on_a_promise_resolving_to_its_argument():
    """`run_sync(js_async_identity(obj))` gives `obj` back (the proxy of
    `obj` that JavaScript got for the call must still be usable when the
    waiting Python code continues)."""
    identity = run_js("async (x) => x")
    obj = object()
    assert pyjs.run_sync(identity(obj)) is obj
    # (the same with await, which always worked)
    assert await identity(obj) is obj


@pytest.mark.skipif(not pyjs.jspi_enabled(), reason="needs JSPI")
async def test_call_promising_from_an_animation_frame_callback_starts_later():
    """A task (`callPromising`) is only ever started when no other wasm code
    is running: its C stack data may be placed anywhere. Python called from
    a `requestAnimationFrame` callback is such running code; a callPromising
    made there must wait for it to finish, not start inside it."""
    if not hasattr(pyjs.js, "requestAnimationFrame"):
        pytest.skip("no requestAnimationFrame")
    log = []
    done = asyncio.get_event_loop().create_future()

    def task():
        log.append("task runs")

    proxy = pyjs.create_proxy(task)
    start = run_js("(f) => { globalThis.__pending = f.callPromising(); }")

    def frame(time_ms):
        start(proxy)
        log.append("frame callback returns")
        done.set_result(None)
        return False  # one frame only

    loop = pyjs.request_animation_frame_loop(frame)
    try:
        await asyncio.wait_for(done, 30)
        await run_js("globalThis.__pending")
    finally:
        loop.cancel()
        proxy.destroy()
        run_js("delete globalThis.__pending")
    assert log == ["frame callback returns", "task runs"], log
