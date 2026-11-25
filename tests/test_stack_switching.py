"""Several Python stacks suspended in run_sync at the same time (JSPI).

Each "task" here is a promising call (`proxy.callPromising(...)`) of a plain
Python function that suspends in `pyjs.run_sync` on a promise the TEST
resolves. So the order in which tasks resume is chosen by the test (all
permutations, seeded random orders), never by timers: the tests are
deterministic.

What is checked after every resumption: the task's own data is intact
(locals, the Python frames, data on the C stack of C functions between the
frames, the exception being handled, contextvars), which is what
src/stack_switching.c (thread state) and src/js/stack_state.ts (C stack)
move out of the way and back.

Without JSPI the tests return right away (the no-jspi run checks the
fallback in test_jspi.py).
"""

import asyncio
import contextvars
import gc
import itertools
import random
import sys
import weakref

import pyjs
from pyjs import js
from pyjs.core import _module

_js_deferred = js.Function(
    """
    let resolve, reject;
    const promise = new Promise((a, b) => { resolve = a; reject = b; });
    return {promise, resolve, reject};
    """
)


class Deferred:
    """a JS promise the test settles itself"""

    def __init__(self):
        d = _js_deferred()
        self.promise = d.promise
        self.resolve = d.resolve
        self.reject = d.reject


def suspended():
    """number of Python stacks suspended in run_sync"""
    return int(_module._jspi_suspended_count())


def tracked():
    """number of suspended stacks with data on the C stack (stack_state.ts)"""
    return int(_module._jspi_stack_state_count())


class Tasks:
    """Start Python functions as promising calls (tasks) and drive them.

    `start(fn, *args)` returns once the task has suspended (or finished):
    `fn` resolves `ready` (its first argument) right before run_sync, and
    run_sync suspends synchronously after that, before the test runs again.
    """

    def __init__(self):
        self.proxies = []
        self.done = []

    async def start(self, fn, *args):
        ready = Deferred()
        proxy = pyjs.create_proxy(fn)
        self.proxies.append(proxy)
        self.done.append(proxy.callPromising(ready.resolve, *args))
        await ready.promise

    async def finish(self):
        """wait for all tasks; returns their results"""
        try:
            return [await d for d in self.done]
        finally:
            for proxy in self.proxies:
                proxy.destroy()


def deep_through_c(depth, fn):
    """call fn() `depth` levels down, each level through C functions (map /
    list / sorted with a key), so that C frames with data on the C stack lie
    between the Python frames (Python -> Python calls alone do not use the
    C stack)"""
    if depth == 0:
        return fn()
    big = list(range(depth))  # a local that must survive
    out = []
    # (sorted returns the list itself: the value comes back through `out`)
    sorted([0], key=lambda _: out.extend(map(lambda _: deep_through_c(depth - 1, fn), [0])))
    assert big == list(range(depth))
    return out[0]


def check_baseline(before_suspended, before_tracked):
    assert suspended() == before_suspended, (suspended(), before_suspended)
    assert tracked() <= before_tracked, (tracked(), before_tracked)


# ---------------------------------------------------------------------------
# resumption orders
# ---------------------------------------------------------------------------
async def _run_in_order(n, order, depths):
    """n tasks suspend (at different C stack depths), resume in `order`"""
    log = []
    deferreds = [Deferred() for _ in range(n)]
    acks = [Deferred() for _ in range(n)]

    def task(ready, i):
        marker = [i] * 100
        cv = contextvars.ContextVar("cv")
        cv.set(i)

        def wait():
            ready()
            value = pyjs.run_sync(deferreds[i].promise)
            # everything of this task is back in place
            assert marker == [i] * 100
            assert cv.get() == i
            return value

        value = deep_through_c(depths[i], wait)
        log.append((i, value))
        acks[i].resolve(None)
        return value

    tasks = Tasks()
    for i in range(n):
        await tasks.start(task, i)
    assert suspended() >= n
    for i in order:
        deferreds[i].resolve(f"v{i}")
        await acks[i].promise
    results = await tasks.finish()
    assert log == [(i, f"v{i}") for i in order], log
    assert results == [f"v{i}" for i in range(n)]


async def test_every_permutation():
    if not pyjs.jspi_enabled():
        return
    before = suspended(), tracked()
    for order in itertools.permutations(range(4)):
        await _run_in_order(4, order, depths=[0, 3, 1, 5])
    check_baseline(*before)


async def test_seeded_random_orders():
    if not pyjs.jspi_enabled():
        return
    before = suspended(), tracked()
    rng = random.Random(1234)
    for _ in range(10):
        n = rng.randint(2, 12)
        order = list(range(n))
        rng.shuffle(order)
        depths = [rng.randint(0, 20) for _ in range(n)]
        await _run_in_order(n, order, depths)
    check_baseline(*before)


async def test_many_suspensions_per_task():
    """each task suspends several times; every round resumes them in another
    random order (stack data evicted and restored again and again)"""
    if not pyjs.jspi_enabled():
        return
    before = suspended(), tracked()
    rng = random.Random(42)
    n, rounds = 8, 6
    deferreds = [[Deferred() for _ in range(rounds)] for _ in range(n)]
    acks = [[Deferred() for _ in range(rounds)] for _ in range(n)]
    log = []

    def task(ready, i):
        total = 0
        for r in range(rounds):

            def wait():
                if r == 0:
                    ready()
                return pyjs.run_sync(deferreds[i][r].promise)

            # a different depth each time: the task's stack size changes
            total += deep_through_c((i * 7 + r * 3) % 15, wait)
            log.append((r, i))
            acks[i][r].resolve(None)
        return total

    tasks = Tasks()
    for i in range(n):
        await tasks.start(task, i)
    for r in range(rounds):
        order = list(range(n))
        rng.shuffle(order)
        for i in order:
            deferreds[i][r].resolve(i * 1000 + r)
            await acks[i][r].promise
        assert [i for rr, i in log if rr == r] == order
    results = await tasks.finish()
    assert results == [sum(i * 1000 + r for r in range(rounds)) for i in range(n)]
    check_baseline(*before)


async def test_stress_many_tasks():
    """200 tasks suspended at once, resumed in a seeded random order, twice"""
    if not pyjs.jspi_enabled():
        return
    before = suspended(), tracked()
    rng = random.Random(7)
    n = 200
    first = [Deferred() for _ in range(n)]
    second = [Deferred() for _ in range(n)]
    acks = [Deferred() for _ in range(n)]

    def task(ready, i):
        data = bytes([i % 256]) * (i + 1)
        ready()
        a = pyjs.run_sync(first[i].promise)
        b = deep_through_c(i % 10, lambda: pyjs.run_sync(second[i].promise))
        assert data == bytes([i % 256]) * (i + 1)
        acks[i].resolve(None)
        return a + b

    tasks = Tasks()
    for i in range(n):
        await tasks.start(task, i)
    order = list(range(n))
    rng.shuffle(order)
    for i in order:
        first[i].resolve(i)
    rng.shuffle(order)
    for i in order:
        second[i].resolve(10 * i)
        await acks[i].promise
    assert await tasks.finish() == [11 * i for i in range(n)]
    check_baseline(*before)


# ---------------------------------------------------------------------------
# exceptions
# ---------------------------------------------------------------------------
async def test_rejections_go_to_the_right_task():
    if not pyjs.jspi_enabled():
        return
    deferreds = [Deferred() for _ in range(4)]

    def task(ready, i):
        ready()
        try:
            pyjs.run_sync(deferreds[i].promise)
        except pyjs.JSException as err:
            return f"{i}: {err.message}"
        return f"{i}: ok"

    tasks = Tasks()
    for i in range(4):
        await tasks.start(task, i)
    deferreds[2].reject(js.Error.new("two"))
    deferreds[0].resolve(None)
    deferreds[3].reject(js.Error.new("three"))
    deferreds[1].resolve(None)
    assert await tasks.finish() == ["0: ok", "1: ok", "2: two", "3: three"]


async def test_exception_being_handled_is_per_task():
    """sys.exception() inside an except block survives other tasks handling
    their own exceptions meanwhile"""
    if not pyjs.jspi_enabled():
        return
    deferreds = [Deferred() for _ in range(3)]

    def task(ready, i):
        try:
            raise KeyError(i)
        except KeyError:
            ready()
            pyjs.run_sync(deferreds[i].promise)
            seen = sys.exception()
        assert sys.exception() is None
        return seen.args[0]

    tasks = Tasks()
    for i in range(3):
        await tasks.start(task, i)
    for i in (1, 2, 0):
        deferreds[i].resolve(None)
    assert await tasks.finish() == [0, 1, 2]


async def test_task_raises_after_resume():
    if not pyjs.jspi_enabled():
        return
    deferreds = [Deferred() for _ in range(2)]

    def task(ready, i):
        ready()
        pyjs.run_sync(deferreds[i].promise)
        if i == 0:
            raise ValueError("task 0")
        return i

    tasks = Tasks()
    for i in range(2):
        await tasks.start(task, i)
    deferreds[1].resolve(None)
    deferreds[0].resolve(None)
    try:
        await tasks.finish()
    except Exception as err:  # the PythonError of task 0 as JSException
        assert "task 0" in str(err), str(err)
    else:
        raise AssertionError("expected the error of task 0")


# ---------------------------------------------------------------------------
# generators, asyncio, contextvars
# ---------------------------------------------------------------------------
async def test_generators_suspended_inside_next():
    if not pyjs.jspi_enabled():
        return
    deferreds = [[Deferred() for _ in range(3)] for _ in range(2)]

    def gen(i):
        for r in range(3):
            yield pyjs.run_sync(deferreds[i][r].promise)

    def task(ready, i):
        g = gen(i)
        ready()
        return list(g)

    tasks = Tasks()
    for i in range(2):
        await tasks.start(task, i)
    for r in range(3):
        for i in (1, 0) if r % 2 else (0, 1):
            deferreds[i][r].resolve(f"{i}{r}")
            await asyncio.sleep(0)
    assert await tasks.finish() == [["00", "01", "02"], ["10", "11", "12"]]


async def test_asyncio_tasks_suspend_concurrently():
    """steps of asyncio tasks are promising calls too: several of them can be
    suspended in run_sync at once"""
    if not pyjs.jspi_enabled():
        return
    deferreds = [Deferred() for _ in range(5)]
    started = [Deferred() for _ in range(5)]
    order = []

    async def worker(i):
        started[i].resolve(None)
        value = pyjs.run_sync(deferreds[i].promise)
        order.append(i)
        return value

    tasks = [asyncio.ensure_future(worker(i)) for i in range(5)]
    for i in range(5):
        await started[i].promise
    for i in (3, 1, 4, 0, 2):
        deferreds[i].resolve(i * i)
    assert list(await asyncio.gather(*tasks)) == [0, 1, 4, 9, 16]
    assert sorted(order) == list(range(5))


async def test_current_task_per_stack():
    """asyncio's current task is part of what is switched"""
    if not pyjs.jspi_enabled():
        return
    deferreds = [Deferred() for _ in range(3)]
    started = [Deferred() for _ in range(3)]

    async def worker(i):
        me = asyncio.current_task()
        started[i].resolve(None)
        pyjs.run_sync(deferreds[i].promise)
        assert asyncio.current_task() is me
        return i

    tasks = [asyncio.ensure_future(worker(i)) for i in range(3)]
    for i in range(3):
        await started[i].promise
    for i in (2, 0, 1):
        deferreds[i].resolve(None)
    assert list(await asyncio.gather(*tasks)) == [0, 1, 2]


async def test_cancel_while_suspended():
    """a task suspended in run_sync cannot be interrupted: cancel() takes
    effect at its next await"""
    if not pyjs.jspi_enabled():
        return
    deferred = Deferred()
    started = Deferred()
    steps = []

    async def worker():
        started.resolve(None)
        steps.append(pyjs.run_sync(deferred.promise))
        await asyncio.sleep(0)
        steps.append("not reached")

    task = asyncio.ensure_future(worker())
    await started.promise
    task.cancel()
    deferred.resolve("resumed")
    try:
        await task
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("expected CancelledError")
    assert steps == ["resumed"]


async def test_run_until_complete_blocks():
    if not pyjs.jspi_enabled():
        return
    loop = asyncio.get_event_loop()

    async def coro():
        await asyncio.sleep(0)
        return 5

    assert loop.run_until_complete(coro()) == 5
    assert loop.run_until_complete(js.Promise.resolve(6)) == 6


async def test_sync_entry_while_tasks_suspended():
    """a synchronous JS -> Python call (an event handler) while tasks are
    suspended: cannot suspend itself, does not see the tasks' contextvars"""
    if not pyjs.jspi_enabled():
        return
    cv = contextvars.ContextVar("cv", default="outer")
    deferreds = [Deferred() for _ in range(2)]
    seen = []

    def task(ready, i):
        cv.set(f"task {i}")
        ready()
        pyjs.run_sync(deferreds[i].promise)
        return cv.get()

    handled = Deferred()

    def handler():
        seen.append((pyjs.can_run_sync(), cv.get()))
        handled.resolve(None)

    tasks = Tasks()
    for i in range(2):
        await tasks.start(task, i)
    # a JS event (a timer) calls Python synchronously
    js.setTimeout(pyjs.create_once_callable(handler), 0)
    await handled.promise
    deferreds[0].resolve(None)
    deferreds[1].resolve(None)
    assert await tasks.finish() == ["task 0", "task 1"]
    assert seen == [(False, "outer")], seen


# ---------------------------------------------------------------------------
# garbage collection
# ---------------------------------------------------------------------------
class _Obj:
    pass


async def test_gc_while_suspended():
    """objects only referenced by a suspended task's frames survive
    gc.collect() (also reference cycles), and are freed after it finished"""
    if not pyjs.jspi_enabled():
        return
    deferred = Deferred()
    refs = []

    def task(ready):
        obj = _Obj()
        obj.cycle = obj
        refs.append(weakref.ref(obj))
        ready()
        pyjs.run_sync(deferred.promise)
        return obj.cycle is obj

    tasks = Tasks()
    await tasks.start(task)
    gc.collect()
    assert refs[0]() is not None
    deferred.resolve(None)
    assert await tasks.finish() == [True]
    gc.collect()
    assert refs[0]() is None


async def test_gc_while_evicted():
    """gc.collect() in a task whose C stack data overwrote the data of
    suspended ones (evicted to a copy), then all of them resume intact (what
    pyodide's test_gc_with_evicted_suspended_task checks)"""
    if not pyjs.jspi_enabled():
        return
    n = 4
    deferreds = [Deferred() for _ in range(n)]
    acks = [Deferred() for _ in range(n)]

    def task(ready, i):
        objs = [_Obj() for _ in range(50)]
        for o in objs:
            o.cycle = o
            o.i = i

        def wait():
            ready()
            pyjs.run_sync(deferreds[i].promise)
            # the deepest one collects while the others are evicted
            gc.collect()
            return all(o.i == i and o.cycle is o for o in objs)

        ok = deep_through_c(5 + 10 * (n - i), wait)
        acks[i].resolve(None)
        return ok

    tasks = Tasks()
    for i in range(n):
        await tasks.start(task, i)
    for i in reversed(range(n)):
        deferreds[i].resolve(None)
        await acks[i].promise
    assert await tasks.finish() == [True] * n


# ---------------------------------------------------------------------------
# bookkeeping
# ---------------------------------------------------------------------------
async def test_counts_back_to_baseline():
    """nothing of a finished task stays tracked (the stack-leak check)"""
    if not pyjs.jspi_enabled():
        return
    before = suspended(), tracked()
    deferreds = [Deferred() for _ in range(5)]

    def task(ready, i):
        ready()
        return deep_through_c(i, lambda: pyjs.run_sync(deferreds[i].promise))

    tasks = Tasks()
    for i in range(5):
        await tasks.start(task, i)
    assert suspended() == before[0] + 5
    for i in (4, 0, 2, 1, 3):
        deferreds[i].resolve(i)
    assert await tasks.finish() == list(range(5))
    check_baseline(*before)
