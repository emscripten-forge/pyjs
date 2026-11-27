"""Async: the asyncio <-> browser event loop bridge (pyjs.WebLoop).

WebLoop.call_soon schedules every callback with ``setTimeout(cb, 0)``. Browsers
clamp nested timeouts (nesting level >= 5) to >= 4ms, so anything that goes
through call_soon (``asyncio.sleep(0)``, waking a task after a future resolves,
awaiting a JS promise, ...) may pay that clamp.

The ``raw_js_*`` benchmarks await JS promises resolved by different browser
scheduling primitives to show what each primitive costs. Note that awaiting
any JS promise from python additionally goes through the asyncio Future /
task wake-up path (i.e. call_soon).
"""

import asyncio

from compat import can_run_sync, create_proxy, js, run_sync
from harness import Skip

_resolved_promise = js.Function("return Promise.resolve(1)")
_settimeout0_promise = js.Function("return new Promise(r => setTimeout(r, 0))")
_microtask_promise = js.Function("return new Promise(r => queueMicrotask(r))")
_messagechannel_promise = js.Function(
    """
    const ch = new MessageChannel();
    return new Promise(r => { ch.port1.onmessage = () => { ch.port1.close(); r(); }; ch.port2.postMessage(0); });
    """
)

# JS-only reference: N sequential setTimeout(0) / MessageChannel hops measured
# entirely in JS (no python involved), awaited once from python.
N_JS = 50
_js_loop_settimeout0 = js.Function(
    "n",
    """
    return (async () => {
        for (let i = 0; i < n; i++) { await new Promise(r => setTimeout(r, 0)); }
    })();
    """,
)
_js_loop_messagechannel = js.Function(
    "n",
    """
    return (async () => {
        const ch = new MessageChannel();
        let resolve = null;
        ch.port1.onmessage = () => resolve();
        for (let i = 0; i < n; i++) {
            await new Promise(r => { resolve = r; ch.port2.postMessage(0); });
        }
        ch.port1.close();
    })();
    """,
)


async def bench_asyncio_sleep_0(benchmark):
    await benchmark.aio(asyncio.sleep, 0)


async def bench_asyncio_sleep_1ms(benchmark):
    # Not the same operation in both runtimes: pyodide runs delays <= 2 ms at
    # once (its scheduleCallback uses the MessageChannel then, without
    # waiting), pyjs waits them (setTimeout). See asyncio_sleep_5ms for a delay
    # both really sleep.
    await benchmark.aio(asyncio.sleep, 0.001)


async def bench_asyncio_sleep_5ms(benchmark):
    # above pyodide's 2 ms threshold: both really sleep (setTimeout); above
    # 4 ms the browser's clamping of nested setTimeout hits both alike
    await benchmark.aio(asyncio.sleep, 0.005)


async def bench_asyncio_create_task_noop(benchmark):
    async def noop():
        pass

    async def spawn():
        await asyncio.create_task(noop())

    await benchmark.aio(spawn)


async def bench_asyncio_future_call_soon_roundtrip(benchmark):
    loop = asyncio.get_running_loop()

    async def roundtrip():
        fut = loop.create_future()
        loop.call_soon(fut.set_result, None)
        await fut

    await benchmark.aio(roundtrip)


async def bench_asyncio_gather_10_sleep_0(benchmark):
    async def gather():
        await asyncio.gather(*[asyncio.sleep(0) for _ in range(10)])

    await benchmark.aio(gather)


async def bench_await_js_resolved_promise(benchmark):
    async def f():
        await _resolved_promise()

    await benchmark.aio(f)


async def bench_await_js_microtask_promise(benchmark):
    async def f():
        await _microtask_promise()

    await benchmark.aio(f)


async def bench_await_js_messagechannel_promise(benchmark):
    async def f():
        await _messagechannel_promise()

    await benchmark.aio(f)


async def bench_await_js_settimeout0_promise(benchmark):
    async def f():
        await _settimeout0_promise()

    await benchmark.aio(f)


async def bench_raw_js_settimeout0_hop(benchmark):
    # pure JS: sequential setTimeout(0) hops (shows the 4ms nesting clamp)
    async def f():
        await _js_loop_settimeout0(N_JS)

    await benchmark.aio(f, ops=N_JS)


async def bench_raw_js_messagechannel_hop(benchmark):
    # pure JS: sequential MessageChannel hops (no clamping)
    async def f():
        await _js_loop_messagechannel(N_JS)

    await benchmark.aio(f, ops=N_JS)


# JSPI: suspending the Python stack (run_sync) and entering Python with a call
# that may suspend (callPromising). Both take their turn in the event loop's
# queue (as in pyodide): run_sync resumes through an asyncio future, a
# callPromising task starts in a later step of the loop.

N_CALLS = 20
# N sequential `await f.callPromising()`, measured in JS
_js_loop_call_promising = js.Function(
    "f",
    "n",
    """
    return (async () => {
        for (let i = 0; i < n; i++) { await f.callPromising(); }
    })();
    """,
)


async def bench_run_sync_resolved_promise(benchmark):
    # (this coroutine runs in a step of an asyncio task, which may suspend)
    if not can_run_sync():
        raise Skip("needs JSPI")

    def f():
        run_sync(_resolved_promise())

    benchmark(f)


async def bench_call_promising_noop(benchmark):
    if not can_run_sync():
        raise Skip("needs JSPI")
    proxy = create_proxy(lambda: None)
    try:

        async def f():
            await _js_loop_call_promising(proxy, N_CALLS)

        await benchmark.aio(f, ops=N_CALLS)
    finally:
        proxy.destroy()
