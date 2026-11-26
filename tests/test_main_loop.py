"""pyjs.set_main_loop_callback / cancel_main_loop (emscripten's main loop)
and the asyncio loop policy."""

import asyncio
import warnings

import pytest

import pyjs


async def _calls(n, fps):
    """start a main loop, wait for `n` calls, cancel it: the `dt` values"""
    done = asyncio.get_event_loop().create_future()
    dts = []

    def callback(dt):
        dts.append(dt)
        if len(dts) == n and not done.done():
            done.set_result(None)

    pyjs.set_main_loop_callback(callback, fps)
    try:
        # (a hang guard only)
        await asyncio.wait_for(done, 30)
    finally:
        pyjs.cancel_main_loop()
    return dts


async def test_main_loop_calls_and_stops():
    dts = await _calls(3, fps=100)
    assert len(dts) >= 3
    assert all(dt >= 0 for dt in dts)
    # after cancel_main_loop no more calls
    count = len(dts)
    await asyncio.sleep(0.1)
    assert len(dts) == count


async def test_main_loop_can_be_started_again():
    """cancel, then a new callback (the loop must not be stuck in the empty
    loop cancel_main_loop leaves behind)"""
    await _calls(2, fps=100)
    assert len(await _calls(2, fps=100)) >= 2


async def test_replacing_a_running_main_loop_warns():
    first = []
    pyjs.set_main_loop_callback(first.append, 100)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            done = asyncio.get_event_loop().create_future()
            pyjs.set_main_loop_callback(lambda dt: done.done() or done.set_result(None), 100)
        assert any("already set" in str(w.message) for w in caught)
        await asyncio.wait_for(done, 30)
    finally:
        pyjs.cancel_main_loop()


def test_cancel_without_a_main_loop_warns():
    with pytest.warns(UserWarning, match="No main loop"):
        pyjs.cancel_main_loop()


def test_event_loop_policy():
    """the policy hands out the one WebLoop: the same loop every time, also
    from asyncio.get_event_loop()"""
    policy = asyncio.get_event_loop_policy()
    assert isinstance(policy, pyjs.WebLoopPolicy)
    loop = policy.get_event_loop()
    assert isinstance(loop, pyjs.WebLoop)
    assert policy.get_event_loop() is loop
    assert asyncio.get_event_loop() is loop


def test_run_until_complete_without_suspension_returns_a_future():
    """where the stack cannot be suspended (a synchronous JavaScript ->
    Python call, like an event handler), run_until_complete schedules and
    returns the future"""
    loop = asyncio.get_event_loop()

    async def seven():
        return 7

    def handler():
        assert not pyjs.can_run_sync()
        return loop.run_until_complete(seven())

    future = pyjs.js.Function("f", "return f();")(handler)
    assert isinstance(future, asyncio.Future)
    # (it runs on the event loop later; nothing waits for it here)
    future.add_done_callback(lambda f: f.result())
