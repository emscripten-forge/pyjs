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

from pyjs import js

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
    await benchmark.aio(asyncio.sleep, 0.001)


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
