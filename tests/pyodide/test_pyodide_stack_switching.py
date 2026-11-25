# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Derived from pyodide (src/tests/test_stack_switching.py, release 314.0.8), modified for pyjs.
#
# Left out:
# - the fixture assert_no_stack_leak (compares `_module.stackSave()` before
#   and after every test): fixtures with teardown do not work for the async
#   tests here
# - test_syncify_not_supported: needs a fresh page (loadPyodide after
#   deleting WebAssembly.Suspending)
# - test_syncify2: package loading (loadPackage("micropip"))
# - test_syncify_getset: needs pyodide's test package test-fpcast
# - test_cpp_exceptions_and_syncify: needs pyodide's test package
#   test-cpp-exceptions and `_module` internals
# - test_signal_handler_runs_inside_promising_task: writes pyodide's signal
#   words in the wasm memory (`_module.__Py_emscripten_signal_in_memory`)
# - test_gc_with_evicted_suspended_task: overwrites the wasm stack of a
#   suspended task (`_module.stackSave`, `HEAPU8.fill`): a regression test
#   for pyodide's implementation of several suspended stacks
#
# Changes beyond the ones described in README.md:
# - `run_js_async` runs a JS snippet like pyodide's host driver does: not
#   called from Python. Afterwards it resolves the promises the snippet made
#   and waits until no Python stack is suspended any more, so that a failed
#   test (pyjs: one suspended stack at a time) does not disturb the next one.
import asyncio
import sys

import pytest

import pyodide_helpers  # noqa: F401  (the JS helpers assert, assertThrows, ...)
from pyodide.code import run_js
from pyodide.ffi import JSProxy, can_run_sync
from pyodide_helpers import requires_jspi

MULTIPLE_STACKS = "pyjs: no several suspended Python stacks at once (run_sync raises in the second)"
NO_RUN_UNTIL_COMPLETE = "pyjs: run_until_complete does not block (it only schedules, also with JSPI)"
NO_CONTEXT_COPY = (
    "pyjs differs: a promising call runs in the context of its caller, "
    "pyodide runs it in a copy (like an asyncio task)"
)

run_js(
    """
    // of pyodide's test page
    globalThis.sleep = function (ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
    };
    """
)

# Runs the body of an async function, see run_js_async.
_run_snippet = run_js(
    """
    (async function (body) {
        // not called from Python: start in a new task of the event loop
        await new Promise((resolve) => setTimeout(resolve, 0));
        // `Promise` inside the snippet: remembers how to resolve the
        // promises the snippet creates
        const resolvers = [];
        class TrackedPromise extends Promise {
            constructor(executor) {
                super((resolve, reject) => {
                    resolvers.push(resolve);
                    executor(resolve, reject);
                });
            }
        }
        const AsyncFunction = (async () => {}).constructor;
        try {
            return await new AsyncFunction("Promise", body)(TrackedPromise);
        } finally {
            // a Python stack that still waits for one of the promises (the
            // snippet failed half way) goes on
            for (const resolve of resolvers) {
                resolve();
            }
        }
    })
    """
)


async def no_suspended_stack():
    """wait until no Python stack is suspended in run_sync any more (called
    from a step of an asyncio task, can_run_sync() is False exactly then)"""
    for _ in range(1000):
        if can_run_sync():
            return
        await asyncio.sleep(0.01)


async def run_js_async(code, timeout=60):
    """pyodide's `selenium.run_js(code)`: the code is the body of an async
    function. (`timeout`: only a guard against a promise that never settles.)"""
    try:
        result = await asyncio.wait_for(_run_snippet(code), timeout)
    finally:
        await no_suspended_stack()
    # arrays / objects as list / dict, like the values the host gets
    return result.to_py() if isinstance(result, JSProxy) else result


@requires_jspi
def test_syncify_awaitable_types_accept():
    from asyncio import create_task, gather, sleep

    from js import sleep as js_sleep
    from pyodide.code import run_js
    from pyodide.ffi import run_sync

    async def test():
        await sleep(0.1)
        return 7

    assert run_sync(test()) == 7
    assert run_sync(create_task(test())) == 7
    run_sync(sleep(0.1))
    run_sync(js_sleep(100))
    res = run_sync(gather(test(), sleep(0.1), js_sleep(100), js_sleep(100)))
    assert list(res) == [7, None, None, None]
    p = run_js("[sleep(100)]")[0]
    run_sync(p)


@requires_jspi
def test_syncify_awaitable_type_errors():
    import pytest

    from pyodide.ffi import run_sync

    with pytest.raises(TypeError):
        run_sync(1)  # type:ignore[arg-type]
    with pytest.raises(TypeError):
        run_sync(None)  # type:ignore[arg-type]
    with pytest.raises(TypeError):
        run_sync([1, 2, 3])  # type:ignore[arg-type]
    with pytest.raises(TypeError):
        run_sync(iter([1, 2, 3]))  # type:ignore[arg-type]

    def f():
        yield 1
        yield 2
        yield 3

    with pytest.raises(TypeError):
        run_sync(f())


@requires_jspi
def test_syncify1():
    from pyodide.code import run_js
    from pyodide.ffi import run_sync

    test = run_js(
        """
        (async function test() {
            await sleep(1000);
            return 7;
        })
        """
    )
    assert run_sync(test()) == 7


@requires_jspi
def test_syncify_error():
    import pytest

    from pyodide.code import run_js
    from pyodide.ffi import JSException, run_sync

    asyncThrow = run_js(
        """
        (async function asyncThrow(){
            throw new Error("hi");
        })
        """
    )

    with pytest.raises(JSException, match="hi"):
        run_sync(asyncThrow())


@requires_jspi
def test_syncify_null():
    from pyodide.code import run_js
    from pyodide.ffi import jsnull, run_sync

    asyncNull = run_js(
        """
        (async function asyncThrow(){
            await sleep(50);
            return null;
        })
        """
    )
    assert run_sync(asyncNull()) is jsnull


@requires_jspi
@pytest.mark.parametrize(
    "debug", [False, pytest.param(True, marks=pytest.mark.xfail(reason="pyjs: no setDebug"))]
)
async def test_syncify_no_suspender(debug):
    # In debug mode, destroying the temporary proxy used to call repr() while
    # the RuntimeError was set, which lost it and raised a SystemError instead.
    if not debug:
        # pyjs: no setDebug. Without debug mode there is nothing to switch.
        await _check_syncify_no_suspender()
        return
    orig = await run_js_async(f"return pyjs.setDebug({str(debug).lower()});")
    try:
        await _check_syncify_no_suspender()
    finally:
        await run_js_async(f"pyjs.setDebug({str(orig).lower()});")


async def _check_syncify_no_suspender():
    # (the message of pyodide: "Cannot stack switch")
    await run_js_async(
        """
        pyjs.runPython(`
            from pyodide.code import run_js
            from pyodide.ffi import run_sync
            import pytest

            test = run_js(
                '''
                (async function test() {
                    await sleep(1000);
                    return 7;
                })
                '''
            )
            with pytest.raises(RuntimeError, match="run_sync cannot be used here"):
                run_sync(test())
            del test
        `);
        """
    )


@requires_jspi
@pytest.mark.skip(reason="Will fix in a followup")
def test_syncify_ctypes():
    from pyodide.code import run_js
    from pyodide.ffi import run_sync

    test = run_js(
        """
        (async function test() {
            await sleep(1000);
            return 7;
        })
        """
    )

    def wrapper():
        return run_sync(test())

    from ctypes import py_object, pythonapi

    pythonapi.PyObject_CallNoArgs.argtypes = [py_object]
    pythonapi.PyObject_CallNoArgs.restype = py_object
    assert pythonapi.PyObject_CallNoArgs(wrapper) == 7


@requires_jspi
@pytest.mark.xfail(reason=MULTIPLE_STACKS)
async def test_two_way_transfer():
    res = await run_js_async(
        """
        pyjs.runPython(`
            from pyodide.ffi import run_sync
            l = []
            def f(n, t):
                from js import sleep
                for i in range(5):
                    run_sync(sleep(t))
                    l.append([n, i])
        `);
        const f = pyjs.globals.get("f");
        await Promise.all([f.callPromising("a", 15), f.callPromising("b", 21)])
        f.destroy();
        const l = pyjs.globals.get("l");
        const res = l.toJs();
        l.destroy();
        return res;
        """
    )
    assert res == [
        ["a", 0],
        ["b", 0],
        ["a", 1],
        ["b", 1],
        ["a", 2],
        ["a", 3],
        ["b", 2],
        ["a", 4],
        ["b", 3],
        ["b", 4],
    ]


@requires_jspi
@pytest.mark.xfail(reason=MULTIPLE_STACKS)
async def test_sync_async_mix():
    res = await run_js_async(
        """
        pyjs.runPython(`
            from pyodide.ffi import run_sync
            from js import sleep

            l = [];
            async def a(t):
                await sleep(t)
                l.append(["a", t])

            def b(t):
                run_sync(sleep(t))
                l.append(["b", t])
        `);
        const a = pyjs.globals.get("a");
        const b = pyjs.globals.get("b");
        const l = pyjs.globals.get("l");

        await Promise.all([
            b.callPromising(300),
            b.callPromising(200),
            b.callPromising(250),
            a(220),
            a(150),
            a(270)
        ]);
        const res = l.toJs();
        for(let p of [a, b, l]) {
            p.destroy();
        }
        return res;
        """
    )
    assert res == [
        ["a", 150],
        ["b", 200],
        ["a", 220],
        ["b", 250],
        ["a", 270],
        ["b", 300],
    ]


@requires_jspi
@pytest.mark.xfail(reason=MULTIPLE_STACKS)
async def test_nested_syncify():
    res = await run_js_async(
        """
        async function f1() {
            await sleep(30);
            return await g1.callPromising();
        }
        async function f2() {
            await sleep(30);
            return await g2.callPromising();
        }
        async function getStuff() {
            await sleep(30);
            return "gotStuff";
        }
        pyjs.globals.set("f1", f1);
        pyjs.globals.set("f2", f2);
        pyjs.globals.set("getStuff", getStuff);

        pyjs.runPython(`
            from pyodide.ffi import run_sync
            from js import sleep
            def g():
                run_sync(sleep(25))
                return run_sync(f1())

            def g1():
                run_sync(sleep(25))
                return run_sync(f2())

            def g2():
                run_sync(sleep(25))
                return run_sync(getStuff())
        `);
        const l = pyjs.runPython("l = []; l")
        const g = pyjs.globals.get("g");
        const g1 = pyjs.globals.get("g1");
        const g2 = pyjs.globals.get("g2");
        const p = [];
        p.push(g.callPromising().then((res) => l.append(res)));
        p.push(pyjs.runPythonAsync(`
            from js import sleep
            for i in range(20):
                run_sync(sleep(9))
                l.append(i)
        `));
        await Promise.all(p);
        const res = l.toJs();
        for(let p of [l, g, g1, g2]) {
            p.destroy()
        }
        return res;
        """
    )
    assert "gotStuff" in res
    del res[res.index("gotStuff")]
    assert res == list(range(20))


@requires_jspi
@pytest.mark.xfail(reason="pyjs: no run_sync in the callbacks of JSPromise.then / finally_")
async def test_promise_methods():
    from asyncio import sleep

    from pyodide.code import run_js
    from pyodide.ffi import run_sync

    async_pass = run_js(
        """
        (async function() {
            return 7;
        })
        """
    )

    async_raise = run_js(
        """
        (async function() {
            throw new Error("oops!");
        })
        """
    )

    def f(*args):
        print("will sleep")
        run_sync(sleep(0.1))
        print("have slept")

    await async_pass().then(f, f)
    await async_raise().then(f, f)
    await async_pass().finally_(f)


@requires_jspi
async def test_throw_from_switcher():
    """
    This used to fail because because a()'s error status got stolen by b(). This
    happens because the promising function is a separate task from the js code
    in callPyObjectSuspending, so the sequence of events goes:

    - enter main task,
        - enter callPyObjectSuspending(a)
            - enter promisingApply(a)
            - sets error flag and returns NULL
        - queue continue callPyObjectSuspending(a) in event loop
          now looks like [main task, continue callPyObjectSuspending(a)]

        - enter b()
            - enter Python
            - returns 7 with error state still set
        - rejects with "SystemError: <function b at 0x1140f20> returned a result with an exception set"
    - queue continue main() in event loop
    - continue callPyObjectSuspending(a)
        - pythonexc2js called attempting to read error flag set by promisingApply(a), fails with
          PythonError: TypeError: Pyodide internal error: no exception type or value

    The solution: at the end of `_pyproxy_apply_promising` we move the error
    flag into errStatus argument. In callPyObjectSuspending when we're ready we
    move the error back from the errorStatus variable into the error flag before
    calling `pythonexc2js()`
    """
    await run_js_async(
        """
        pyjs.runPython(`
            def a():
                raise Exception("hi")
            def b():
                return 7;
        `);
        const a = pyjs.globals.get("a");
        const b = pyjs.globals.get("b");
        const p = a.callPromising();
        assert(() => b() === 7);
        await assertThrowsAsync(async () => await p, "PythonError", "Exception: hi");
        a.destroy();
        b.destroy();
        """
    )


@requires_jspi
@pytest.mark.xfail(reason=MULTIPLE_STACKS)
async def test_switch_from_except_block():
    """Test for issue #4566"""
    result = await run_js_async(
        """
        const result = [];
        pyjs.globals.set("result", result);
        pyjs.runPython(`
            from pyodide.ffi import run_sync, to_js
            import sys
            from js import sleep

            def pe(s):
                result.push(to_js([s, repr(sys.exception())]))

            def g(n):
                pe(f"{n}0")
                try:
                    raise Exception(n)
                except:
                    pe(f"{n}1")
                    run_sync(sleep(10))
                    pe(f"{n}2")
                pe(f"{n}3")
        `);
        const pe = pyjs.globals.get("pe");
        const g = pyjs.globals.get("g");
        const g1 = g.callPromising("a");
        const g2 = g.callPromising("b");
        await pe.callPromising('tt');
        await g1;
        await g2;
        pyjs.globals.delete("result");
        pe.destroy();
        g.destroy();
        return result;
        """
    )
    assert result == [
        ["a0", "None"],
        ["a1", "Exception('a')"],
        ["b0", "None"],
        ["b1", "Exception('b')"],
        ["tt", "None"],
        ["a2", "Exception('a')"],
        ["a3", "None"],
        ["b2", "Exception('b')"],
        ["b3", "None"],
    ]


# Start with just a no-op script
LEAK_SCRIPT1 = """
def test(n):
    pass
"""

LEAK_SCRIPT2 = """
from pyodide.ffi import run_sync
from js import sleep

def test(n):
    run_sync(sleep(1))
"""

LEAK_SCRIPT3 = """
from pyodide.ffi import run_sync
from asyncio import sleep as py_sleep, ensure_future

async def sleep(x):
    await py_sleep(x/1000)

def test(n):
    run_sync(ensure_future(sleep(1)))
"""

LEAK_SCRIPT4 = """
from pyodide.ffi import run_sync
from asyncio import sleep as py_sleep

async def sleep(x):
    await py_sleep(x/1000)

def test(n):
    run_sync(sleep(1))
"""


@requires_jspi
@pytest.mark.parametrize(
    "script",
    [
        LEAK_SCRIPT1,
        # (200 calls at once, each of them suspends)
        pytest.param(LEAK_SCRIPT2, marks=pytest.mark.xfail(reason=MULTIPLE_STACKS)),
        pytest.param(LEAK_SCRIPT3, marks=pytest.mark.xfail(reason=MULTIPLE_STACKS)),
        pytest.param(LEAK_SCRIPT4, marks=pytest.mark.xfail(reason=MULTIPLE_STACKS)),
    ],
)
async def test_memory_leak(script):
    length_change = await run_js_async(
        f"""
        pyjs.runPython(`{script}`);
        """
        """
        const t = pyjs.globals.get("test");
        for (let i = 0; i < 1; i++) {
            let p = [];
            // warm up first to avoid edge problems
            for (let i = 0; i < 200; i++) {
                p.push(t.callPromising(1));
            }
            await Promise.all(p);
        }
        const startLength = pyjs.HEAP32.length;
        for (let i = 0; i < 10; i++) {
            let p = [];
            for (let i = 0; i < 200; i++) {
                p.push(t.callPromising(1));
            }
            await Promise.all(p);
        }
        t.destroy();
        return pyjs.HEAP32.length - startLength;
        """
    )
    assert length_change == 0


@requires_jspi
@pytest.mark.xfail(reason=NO_RUN_UNTIL_COMPLETE)
def test_run_until_complete():
    from asyncio import all_tasks, create_task, gather, get_event_loop, sleep

    from js import sleep as js_sleep
    from pyodide.code import run_js

    loop = get_event_loop()

    async def test():
        await sleep(0.1)
        return 7

    tasks = all_tasks()
    try:
        assert loop.run_until_complete(test()) == 7
        assert loop.run_until_complete(create_task(test())) == 7
        loop.run_until_complete(sleep(0.1))
        loop.run_until_complete(js_sleep(100))
        res = loop.run_until_complete(
            gather(test(), sleep(0.1), js_sleep(100), js_sleep(100))
        )
        assert list(res) == [7, None, None, None]
        p = run_js("[sleep(100).then(() => 99)]")[0]
        assert loop.run_until_complete(p) == 99
    finally:
        # (not in pyodide's test) nothing of a failed test goes on later
        for task in all_tasks() - tasks:
            task.cancel()


@requires_jspi
async def test_can_run_sync():
    results = await run_js_async(
        """
        const results = [];
        pyjs.globals.set("results", results);
        pyjs.runPython(`
            from pyodide.ffi import can_run_sync, to_js
            from pyodide.code import run_js
            def expect(n, val):
                results.append(to_js([n, can_run_sync(), val]))
        `)


        pyjs.runPython(`expect(0, False)`);

        await pyjs.runPythonAsync(`expect(1, True)`);

        pyjs.runPython(`
            def fsync():
               expect(2, False)
        `);
        const fsync = pyjs.globals.get("fsync");
        fsync();
        fsync.destroy();

        pyjs.runPython(`
            def fsync():
                expect(3, True)

            async def fasync():
                fsync()
                expect(4, True)
        `);
        const fasync = pyjs.globals.get("fasync");
        await fasync();
        fasync.destroy();

        await pyjs.runPythonAsync(`
            def fsync():
                expect(5, False)

            run_js("(f) => f()")(fsync)
        `);

        await pyjs.runPythonAsync(`
            def fsync():
                expect(6, True)

            async def fasync():
                fsync()
                expect(7, True)

            await run_js("(f) => f()")(fasync)
        `);

        await pyjs.runPythonAsync(`
            run_js("(x) => Array.from(x)")([])
            expect(8, True)
        `);

        return results;
        """
    )
    assert len(results) == 9
    for idx, [i, res, expected] in enumerate(results):
        assert idx == i
        assert res == expected


@requires_jspi
async def test_async_promising_sync_error():
    await run_js_async(
        """
        const test = pyjs.runPython(`
            def test():
                1/0

            test
        `)

        try {
            await assertThrowsAsync(
                async () => await test.callPromising(),
                "PythonError",
                "division by zero"
            );
        } finally {
            test.destroy();
        }
        """
    )
    # In bad cases, the previous exception was a fatal error but we didn't
    # notice. Check that no fatal error occurred by running Python.
    run_js("pyjs.runPython('')")


@requires_jspi
async def test_async_promising_async_error():
    await run_js_async(
        """
        const test = pyjs.runPython(`
            async def test():
                1/0

            test
        `)

        try {
            await assertThrowsAsync(
                async () => await test.callPromising(),
                "PythonError",
                "division by zero"
            );
        } finally {
            test.destroy();
        }
        """
    )
    # In bad cases, the previous exception was a fatal error but we didn't
    # notice. Check that no fatal error occurred by running Python.
    run_js("pyjs.runPython('')")


@requires_jspi
@pytest.mark.xfail(
    reason="pyjs: no stack switching in a promising call made while Python runs "
    "(a JS function called by Python calls callPromising: run_sync raises)"
)
async def test_return_promising_no_crash():
    """This used to fatally fail.

    The fix was to incref ptrobj before await Module.promisingApply(...), so
    presumably the crash involved the pointer to g getting freed out from
    underneath? I'm honestly not sure how it worked.
    """
    try:
        await run_js_async(
            """
            globalThis.f = function f() {
                return task.callPromising();
            };
            pyjs.runPython(`
                from asyncio import sleep
                from pyodide.ffi import run_sync

                def task():
                    run_sync(sleep(1))

                def g():
                    from js import f
                    return f()
            `);
            const task = pyjs.globals.get("task");
            const g = pyjs.globals.get("g");
            await Promise.all([g(), g()]);
            g.destroy();
            task.destroy();
            """
        )
    finally:
        run_js("delete globalThis.f")


# The following tests cover the thread state ownership model described at the
# top of src/core/stack_switching/pystate.c. A promising task owns a thread
# state of its own for its whole lifetime.

SUSPEND_ON_PROMISE_SETUP = """
    pyjs.runPython(`
        from pyodide.ffi import run_sync

        def suspend_on(p, before=None, after=None):
            if before is not None:
                before()
            run_sync(p)
            if after is not None:
                return after()
    `);
    // Start a promising call that suspends until we resolve the returned
    // trigger. Waits until the task has really suspended before returning.
    const suspend_on = pyjs.globals.get("suspend_on");
    async function startSuspendedTask(before, after) {
        let resolve;
        const p = new Promise((res) => { resolve = res; });
        const done = suspend_on.callPromising(p, before, after);
        // callPromising yields to the event loop before it even enters Python, so
        // we have to wait for the task to actually reach run_sync().
        await new Promise((res) => setTimeout(res, 50));
        return { resolve, done };
    }
"""


@requires_jspi
async def test_contextvars_ambient_context_survives_switch():
    """The context of the event loop turn must not be carried off by a task.

    Previously the suspending task took the caller's thread state with it and
    handed the caller a brand new one, so top level code lost its contextvars for
    the duration of the switch.
    """
    result = await run_js_async(
        """
        pyjs.runPython(`
            import contextvars
            cvar = contextvars.ContextVar("cvar", default="<lost>")
            cvar.set("TOP-LEVEL")
            observe = lambda: cvar.get()
            copied = lambda: contextvars.copy_context().get(cvar, "<absent>")
        `);
        """
        + SUSPEND_ON_PROMISE_SETUP
        + """
        const observe = pyjs.globals.get("observe");
        const copied = pyjs.globals.get("copied");
        const out = { before: observe() };
        const task = await startSuspendedTask();
        out.during = observe();
        out.duringCopyContext = copied();
        task.resolve();
        await task.done;
        out.after = observe();
        suspend_on.destroy();
        observe.destroy();
        copied.destroy();
        return out;
        """
    )
    assert result == {
        "before": "TOP-LEVEL",
        "during": "TOP-LEVEL",
        "duringCopyContext": "TOP-LEVEL",
        "after": "TOP-LEVEL",
    }


@requires_jspi
@pytest.mark.xfail(reason=MULTIPLE_STACKS)
async def test_contextvars_survive_interleaved_switches():
    """Stack switches are not properly nested.

    Resume A, finish A, then resume B. Previously each resume destroyed whichever
    thread state happened to be current, so the event loop's thread state ended up
    recycled and top level contextvars and threading.local() state were lost.
    """
    result = await run_js_async(
        """
        pyjs.runPython(`
            import contextvars, threading
            cvar = contextvars.ContextVar("cvar", default="<lost>")
            cvar.set("TOP-LEVEL")
            tls = threading.local()
            tls.value = "TOP-LEVEL-TLS"
            def observe():
                return [cvar.get(), getattr(tls, "value", "<lost>")]
        `);
        """
        + SUSPEND_ON_PROMISE_SETUP
        + """
        const observe = pyjs.globals.get("observe");
        const a = await startSuspendedTask();
        const b = await startSuspendedTask();
        // Deliberately not LIFO.
        a.resolve();
        await a.done;
        b.resolve();
        await b.done;
        const observed = observe();
        const out = observed.toJs();
        observed.destroy();
        suspend_on.destroy();
        observe.destroy();
        return out;
        """
    )
    assert result == ["TOP-LEVEL", "TOP-LEVEL-TLS"]


@requires_jspi
async def test_contextvars_task_writes_are_isolated():
    """A task inherits a *copy* of its caller's context, like asyncio.Task does.

    So it can read what the caller set, but its own writes don't leak back out to
    the caller or into any later task. Previously a task's writes leaked out
    through the recycled thread state and showed up in a completely unrelated
    stack switch.
    """
    result = await run_js_async(
        """
        pyjs.runPython(`
            import contextvars
            cvar = contextvars.ContextVar("cvar", default="<default>")
            cvar.set("CALLER")
            observe = lambda: cvar.get()
            def poison():
                cvar.set("TASK-ONLY")
        `);
        """
        + SUSPEND_ON_PROMISE_SETUP
        + """
        const observe = pyjs.globals.get("observe");
        const poison = pyjs.globals.get("poison");
        const out = {};
        // A task that reads the caller's context, then overwrites it and keeps the
        // value set across a suspension.
        let task = await startSuspendedTask(poison, observe);
        task.resolve();
        out.insideTask = await task.done;
        out.callerAfterTask = observe();
        // A second, unrelated task must not see the first task's write.
        task = await startSuspendedTask(undefined, observe);
        task.resolve();
        out.insideLaterTask = await task.done;
        suspend_on.destroy();
        observe.destroy();
        poison.destroy();
        return out;
        """
    )
    assert result == {
        "insideTask": "TASK-ONLY",
        "callerAfterTask": "CALLER",
        "insideLaterTask": "CALLER",
    }


@requires_jspi
async def test_contextvars_released_after_task():
    """A recycled thread state must not pin the context it used to hold."""
    alive = await run_js_async(
        """
        pyjs.runPython(`
            import contextvars, gc, weakref
            cvar = contextvars.ContextVar("cvar", default=None)
            ref = None
            class Big:
                pass
            def poison():
                global ref
                o = Big()
                ref = weakref.ref(o)
                cvar.set(o)
            def still_alive():
                gc.collect()
                return ref() is not None
        `);
        """
        + SUSPEND_ON_PROMISE_SETUP
        + """
        const poison = pyjs.globals.get("poison");
        const still_alive = pyjs.globals.get("still_alive");
        let task = await startSuspendedTask(poison);
        task.resolve();
        await task.done;
        // Churn some tasks
        for (let i = 0; i < 15; i++) {
            task = await startSuspendedTask();
            task.resolve();
            await task.done;
        }
        const out = still_alive();
        suspend_on.destroy();
        poison.destroy();
        still_alive.destroy();
        return out;
        """
    )
    assert alive is False


@requires_jspi
@pytest.mark.xfail(reason=MULTIPLE_STACKS)
async def test_contextvars_concurrent_tasks():
    """Concurrent coroutines that syncify in the middle must not see each other's
    contextvars, and tasks they spawn must inherit the right context."""
    import asyncio
    import contextvars

    from js import sleep as js_sleep
    from pyodide.ffi import run_sync

    request_id = contextvars.ContextVar("request_id", default="<none>")

    async def handle(rid, delay):
        request_id.set(rid)
        run_sync(js_sleep(delay))
        assert request_id.get() == rid, f"after run_sync: {request_id.get()}"

        async def child():
            return request_id.get()

        assert await asyncio.ensure_future(child()) == rid
        return request_id.get()

    try:
        # B finishes its switch before A does, so the two switches interleave.
        assert list(await asyncio.gather(handle("REQ-A", 60), handle("REQ-B", 20))) == [
            "REQ-A",
            "REQ-B",
        ]
        assert request_id.get() == "<none>"
    finally:
        # (not in pyodide's test) nothing of a failed test goes on later
        await no_suspended_stack()


@requires_jspi
@pytest.mark.xfail(reason=NO_RUN_UNTIL_COMPLETE)
def test_asyncio_running_loop_in_task():
    """The running event loop lives on the thread state, so a task with a thread
    state of its own has to inherit it from its caller."""
    import asyncio

    from pyodide.code import run_js

    loop = asyncio.get_event_loop()

    async def test():
        assert asyncio.get_running_loop() is loop
        p = run_js("[sleep(50).then(() => 11)]")[0]
        from pyodide.ffi import run_sync

        assert run_sync(p) == 11
        assert asyncio.get_running_loop() is loop
        return 5

    tasks = asyncio.all_tasks()
    try:
        assert loop.run_until_complete(test()) == 5
    finally:
        # (not in pyodide's test) nothing of a failed test goes on later
        for task in asyncio.all_tasks() - tasks:
            task.cancel()


@requires_jspi
async def test_task_does_not_invent_a_running_loop():
    """A task inherits the loop that is really running, not get_event_loop().

    The running loop is recorded on the thread state, so a task has to inherit
    it from its caller. We used to fetch it with asyncio.get_event_loop(), which
    falls back to the thread's *current* loop when nothing is running, and then
    registered whatever came back as the running loop on the task. That made
    asyncio.get_running_loop() incorrectly report a loop that was not running.
    """
    result = await run_js_async(
        """
        pyjs.runPython(`
            import asyncio

            def report():
                try:
                    return type(asyncio.get_running_loop()).__name__
                except RuntimeError as e:
                    return f"RuntimeError: {e}"
        `);
        const report = pyjs.globals.get("report");
        try {
            // WebLoop registers itself as the running loop when it is
            // constructed. Take it back off, so that there is a current event
            // loop for get_event_loop() to fall back to but nothing running.
            const hadRunningLoop = pyjs.runPython(`
                _saved_loop = asyncio._get_running_loop()
                asyncio._set_running_loop(None)
                _saved_loop is not None
            `);
            const clearedOnMain = pyjs.runPython("report()");
            const inTask = await report.callPromising();
            const fallbackLoop = pyjs.runPython(
                "type(asyncio.get_event_loop()).__name__"
            );
            return { hadRunningLoop, clearedOnMain, inTask, fallbackLoop };
        } finally {
            pyjs.runPython(`
                if "_saved_loop" in globals():
                    asyncio._set_running_loop(_saved_loop)
                    del _saved_loop
            `);
            report.destroy();
        }
        """
    )
    # Preconditions: there was a running loop to remove, removing it worked, and
    # get_event_loop() still has something to fall back to.
    assert result["hadRunningLoop"]
    assert result["clearedOnMain"] == "RuntimeError: no running event loop"
    assert result["fallbackLoop"] == "WebLoop"
    # The task must report the same thing its caller would, not the fallback.
    assert result["inTask"] == "RuntimeError: no running event loop"


@requires_jspi
@pytest.mark.xfail(reason=MULTIPLE_STACKS)
async def test_contextvars_three_interleaved_tasks():
    """Three tasks, each suspending twice, resumed in an order unrelated to the
    order they suspended in.

    Each task must keep seeing its own contextvar value across both of its
    suspensions, must have inherited the caller's value on entry, and must not
    disturb the caller's value or each other's.
    """
    result = await run_js_async(
        """
        pyjs.runPython(`
            import contextvars
            from pyodide.ffi import run_sync
            cvar = contextvars.ContextVar("cvar", default="<unset>")
            cvar.set("ROOT")

            def task(name, first, second):
                inherited = cvar.get()
                cvar.set(name)
                run_sync(first)
                after_first = cvar.get()
                run_sync(second)
                return [inherited, after_first, cvar.get()]

            observe = lambda: cvar.get()
        `);
        const task = pyjs.globals.get("task");
        const observe = pyjs.globals.get("observe");
        const tick = () => new Promise((res) => setTimeout(res, 50));

        // Start a task and wait for it to reach its first run_sync().
        const started = {};
        function start(name) {
            let first, second;
            const p1 = new Promise((res) => { first = res; });
            const p2 = new Promise((res) => { second = res; });
            const done = task.callPromising(name, p1, p2);
            started[name] = { first, second, done };
        }
        start("A");
        start("B");
        start("C");
        await tick();
        const duringAll = observe();

        // Release the first suspension in a different order than they started.
        started.C.first();
        await tick();
        started.A.first();
        await tick();
        started.B.first();
        await tick();
        const duringSecond = observe();

        // And the second suspension in yet another order.
        started.B.second();
        started.C.second();
        started.A.second();
        const out = {};
        for (const name of ["A", "B", "C"]) {
            const res = await started[name].done;
            out[name] = res.toJs();
            res.destroy();
        }
        out.duringAll = duringAll;
        out.duringSecond = duringSecond;
        out.atEnd = observe();
        task.destroy();
        observe.destroy();
        return out;
        """
    )
    assert result == {
        # Each task inherits ROOT, then only ever sees its own value.
        "A": ["ROOT", "A", "A"],
        "B": ["ROOT", "B", "B"],
        "C": ["ROOT", "C", "C"],
        # The event loop turn keeps its own context the whole way through.
        "duringAll": "ROOT",
        "duringSecond": "ROOT",
        "atEnd": "ROOT",
    }


@requires_jspi
@pytest.mark.xfail(reason=MULTIPLE_STACKS)
async def test_contextvars_task_spawned_from_running_task():
    """Two parent tasks that each re-enter Python from JS while running.

    A1 suspends, B1 suspends, A1 resumes and calls out to JS which uses
    callPromising() to call back into Python and start A2 (without awaiting it),
    A1 suspends again, A2 starts and suspends. Same for B1/B2. Then they exit in
    the order A1, B1, A2, B2, i.e. the parents finish before their children and
    nothing unwinds in the order it was created.

    Note that A2 inherits the event loop turn's context, not A1's, even though
    A1 is what triggered it. It means callPromising() behaves like "spawn on the
    event loop" rather than like loop.call_soon(), which captures the caller's
    context.
    """
    order, results, observations = await run_js_async(
        """
        const results = [];
        const observations = {};
        pyjs.globals.set("results", results);
        pyjs.runPython(`
            import contextvars
            from pyodide.ffi import run_sync, to_js
            cvar = contextvars.ContextVar("cvar", default="<unset>")
            cvar.set("ROOT")

            def parent(name, first, second, spawn):
                inherited = cvar.get()
                cvar.set(name)
                run_sync(first)
                # Re-enter Python from JS while we are running. This returns a
                # pending promise; we deliberately don't wait for the child.
                spawn()
                mid = cvar.get()
                run_sync(second)
                results.append(to_js([name, inherited, mid, cvar.get()]))
                return name

            def child(name, only):
                inherited = cvar.get()
                cvar.set(name)
                run_sync(only)
                results.append(to_js([name, inherited, cvar.get()]))
                return name

            observe = lambda: cvar.get()
        `);
        const parent = pyjs.globals.get("parent");
        const child = pyjs.globals.get("child");
        const observe = pyjs.globals.get("observe");
        const tick = () => new Promise((res) => setTimeout(res, 50));

        function trigger() {
            let release;
            const promise = new Promise((res) => { release = res; });
            return { promise, release };
        }
        const a1 = { first: trigger(), second: trigger() };
        const b1 = { first: trigger(), second: trigger() };
        const a2 = trigger();
        const b2 = trigger();

        const order = [];
        const children = {};
        // Handed to Python and called from inside the running parent.
        function spawn(name, t) {
            return () => {
                children[name] = child.callPromising(name, t.promise);
            };
        }

        const a1done = parent.callPromising(
            "A1", a1.first.promise, a1.second.promise, spawn("A2", a2));
        await tick();
        const b1done = parent.callPromising(
            "B1", b1.first.promise, b1.second.promise, spawn("B2", b2));
        await tick();
        observations.a1AndB1Suspended = observe();

        // A1 resumes, spawns A2, suspends again; then A2 starts and suspends.
        a1.first.release();
        await tick();
        // Same for B1/B2.
        b1.first.release();
        await tick();
        observations.allFourSuspended = observe();

        // Exit A1, B1, A2, B2 -- parents before children.
        a1.second.release();
        order.push(await a1done);
        await tick();
        observations.afterA1AndNothingElse = observe();

        b1.second.release();
        order.push(await b1done);
        await tick();
        observations.afterBothParents = observe();

        a2.release();
        order.push(await children.A2);
        await tick();
        observations.afterA2 = observe();

        b2.release();
        order.push(await children.B2);
        await tick();
        observations.atEnd = observe();

        parent.destroy();
        child.destroy();
        observe.destroy();
        return [order, results, observations];
        """
    )
    assert order == ["A1", "B1", "A2", "B2"]
    # [name, context inherited on entry, ...context seen after each suspension]
    assert sorted(results) == [
        ["A1", "ROOT", "A1", "A1"],
        ["A2", "ROOT", "A2"],
        ["B1", "ROOT", "B1", "B1"],
        ["B2", "ROOT", "B2"],
    ]
    # The event loop turn keeps its own context no matter how the four tasks
    # interleave, including after some of them have exited.
    assert observations == {
        "a1AndB1Suspended": "ROOT",
        "allFourSuspended": "ROOT",
        "afterA1AndNothingElse": "ROOT",
        "afterBothParents": "ROOT",
        "afterA2": "ROOT",
        "atEnd": "ROOT",
    }


@requires_jspi
async def test_threading_local_shared_with_tasks():
    """threading.local() is shared with calls that stack switch.

    There is only one thread. threading.get_ident() and
    threading.current_thread() report the same thing inside a call that stack
    switches as they do outside one, so threading.local() has to agree with
    them. That needs doing explicitly: each call runs on a thread state of its
    own and threading.local() storage is keyed on the thread state (via
    tstate->threading_local_key) rather than living in the thread dict.
    """
    ident_match, seen, top_level = await run_js_async(
        """
        pyjs.runPython(`
            import threading
            from pyodide.ffi import run_sync
            loc = threading.local()
            loc.v = "TOP"
            top_ident = threading.get_ident()

            def task(name, p):
                before = getattr(loc, "v", "<unset>")
                loc.v = name
                run_sync(p)
                return [before, threading.get_ident() == top_ident]
        `);
        const task = pyjs.globals.get("task");
        const seen = [];
        let identMatch = true;
        // Run the calls one after another, so each one starts after the
        // previous one has finished and released its thread state.
        for (const name of ["A", "B"]) {
            let release;
            const promise = new Promise((res) => { release = res; });
            const done = task.callPromising(name, promise);
            await new Promise((res) => setTimeout(res, 20));
            release();
            const res = await done;
            seen.push(res.get(0));
            identMatch = identMatch && res.get(1);
            res.destroy();
        }
        task.destroy();
        return [identMatch, seen, pyjs.runPython(`loc.v`)];
        """
    )
    # The calls really are on the thread they claim to be on.
    assert ident_match
    # Each call sees what the previous writer left, whether that was top level
    # or another call...
    assert seen == ["TOP", "A"]
    # ...and top level sees what the calls wrote.
    assert top_level == "B"


@requires_jspi
async def test_task_inherits_asyncgen_hooks():
    """sys.set_asyncgen_hooks() applies inside promising tasks.

    The hooks are recorded on the thread state, and a task runs on a thread
    state of its own, so it has to inherit them from its caller. Otherwise an
    async generator created inside a task is never handed to the hook that is
    supposed to arrange for it to be closed.
    """
    # (not in pyodide's test: the hooks are put back)
    hooks = sys.get_asyncgen_hooks()
    try:
        seen = await run_js_async(
            """
            pyjs.runPython(`
                import sys
                from pyodide.ffi import run_sync

                seen = []

                async def agen():
                    yield 1

                def drive():
                    # Start the async generator on this thread state. The firstiter
                    # hook fires on the first __anext__().
                    g = agen()
                    try:
                        g.__anext__().send(None)
                    except StopIteration:
                        pass

                def task(p):
                    # Suspend and resume first, so we also cover the hooks
                    # surviving a round trip through the event loop.
                    run_sync(p)
                    drive()
                    return seen

                sys.set_asyncgen_hooks(
                    firstiter=lambda ag: seen.append(ag.__name__),
                    finalizer=lambda ag: None,
                )
            `);
            const task = pyjs.globals.get("task");
            let release;
            const promise = new Promise((res) => { release = res; });
            const done = task.callPromising(promise);
            await new Promise((res) => setTimeout(res, 20));
            release();
            const res = await done;
            const out = res.toJs();
            res.destroy();
            task.destroy();
            return out;
            """
        )
    finally:
        sys.set_asyncgen_hooks(*hooks)
    assert seen == ["agen"]


@requires_jspi
@pytest.mark.parametrize("hook", ["trace", "profile"])
async def test_task_inherits_trace_and_profile_hooks(hook):
    """settrace() and setprofile() callbacks should fire in promising tasks"""
    result = await run_js_async(
        f'const hookName = "{hook}";\n'
        """
        pyjs.runPython(`
            import sys
            from pyodide.ffi import run_sync

            calls = []

            def hook(frame, event, arg):
                # Only trace call events
                if event == "call":
                    calls.append(frame.f_code.co_name)
                return None

            def inside_task():
                return 1

            def after_removal():
                return 1

            def task(p):
                # Suspend and resume before doing any work to ensure that the
                # hook survives a round trip through the event loop
                run_sync(p)
                inside_task()

            def install(name):
                getattr(sys, "set" + name)(hook)

            def remove(name):
                getattr(sys, "set" + name)(None)
        `);
        const task = pyjs.globals.get("task");
        const install = pyjs.globals.get("install");
        const remove = pyjs.globals.get("remove");
        try {
            install(hookName);
            const {promise, resolve} = Promise.withResolvers();
            const done = task.callPromising(promise);
            await sleep(20);
            resolve();
            await done;
            const sawInsideTask = pyjs.runPython("'inside_task' in calls");
            remove(hookName);
            pyjs.runPython("calls.clear()");
            pyjs.runPython("after_removal()");
            const sawAfterRemoval = pyjs.runPython("'after_removal' in calls");
            return { sawInsideTask, sawAfterRemoval };
        } finally {
            remove(hookName);
            task.destroy();
            install.destroy();
            remove.destroy();
        }
        """
    )
    assert result["sawInsideTask"]
    assert not result["sawAfterRemoval"]


@requires_jspi
async def test_new_event_loop_inside_task():
    """A call that stack switches can create and drive its own event loop.

    WebLoop.__init__ registers itself as the running loop, which records it on
    the current thread state. A call runs on a thread state of its own, so a
    loop built there used to be registered only on a thread state that goes
    away when the call finishes. Its handles run on the event loop's thread
    state, where asyncio's enter_task() then refused to step the task with
    "loop ... is not the running loop", and the call hung forever. This is what
    pytest-asyncio does for every async test.
    """
    result = await run_js_async(
        """
        pyjs.runPython(`
            import asyncio

            async def coro():
                await asyncio.sleep(0)
                return "ok"

            def task():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(coro())
                finally:
                    loop.close()
        `);
        const task = pyjs.globals.get("task");
        const result = await Promise.race([
            task.callPromising(),
            new Promise((res) => setTimeout(() => res("<hung>"), 10000)),
        ]);
        task.destroy();
        return result;
        """
    )
    assert result == "ok"
