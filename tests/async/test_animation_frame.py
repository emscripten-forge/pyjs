import asyncio

import pyjs


# hang guard only (rAF frames are ~16 ms; slow CI runners are fine with this)
_TIMEOUT = 30


def _has_raf():
    """requestAnimationFrame exists (main thread; workers in most browsers)."""
    return pyjs.js.Reflect.has(pyjs.js.globalThis, "requestAnimationFrame")


async def _frames(n):
    """Wait for `n` animation frames (via a second loop)."""
    done = asyncio.get_running_loop().create_future()
    count = 0

    def tick(time_ms):
        nonlocal count
        count += 1
        if count == n:
            done.set_result(None)
            return False
        return True

    pyjs.request_animation_frame_loop(tick)
    await asyncio.wait_for(done, _TIMEOUT)


async def test_animation_frame_loop_stops_on_false():
    """The loop calls the callback once per frame with the frame time and stops
    when it returns False (no further calls)."""
    if not _has_raf():
        print("skip test_animation_frame_loop_stops_on_false: no requestAnimationFrame")
        return
    done = asyncio.get_running_loop().create_future()
    times = []

    def tick(time_ms):
        times.append(time_ms)
        if len(times) == 3:
            done.set_result(None)
            return False
        return True

    loop = pyjs.request_animation_frame_loop(tick)
    assert loop.running
    await asyncio.wait_for(done, _TIMEOUT)
    assert not loop.running
    assert all(isinstance(t, float) for t in times)
    assert times == sorted(times)

    await _frames(3)
    assert len(times) == 3


async def test_animation_frame_loop_cancel():
    """`cancel()` stops the loop before its next frame."""
    if not _has_raf():
        print("skip test_animation_frame_loop_cancel: no requestAnimationFrame")
        return
    calls = []
    loop = pyjs.request_animation_frame_loop(lambda t: calls.append(t) or True)
    loop.cancel()
    assert not loop.running
    await _frames(3)
    assert calls == []


async def test_animation_frame_loop_stops_on_exception():
    """An exception in the callback is printed and stops the loop."""
    if not _has_raf():
        print("skip test_animation_frame_loop_stops_on_exception: no requestAnimationFrame")
        return
    calls = []

    def tick(time_ms):
        calls.append(time_ms)
        raise ValueError("expected error from test_animation_frame_loop_stops_on_exception")

    loop = pyjs.request_animation_frame_loop(tick)
    await _frames(3)
    assert len(calls) == 1
    assert not loop.running
