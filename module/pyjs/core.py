"""What pyjs has beyond the foreign function interface (`pyjs.ffi`):
awaiting across the two languages, the emscripten main loop / animation
frames, and blocking on a promise (`run_sync`, JSPI)."""

import asyncio
import contextvars
import time
import traceback
import warnings

import pyjs_core
from pyjs_core import JSProxy

from .error_handling import JSException, error_to_py
from .ffi import create_once_callable

__all__ = [
    "set_main_loop_callback",
    "cancel_main_loop",
    "AnimationFrameLoop",
    "request_animation_frame_loop",
    "set_canvas",
    "jspi_enabled",
    "can_run_sync",
    "run_sync",
]

_js = pyjs_core.global_this()
_module = pyjs_core.module()


# ---------------------------------------------------------------------------
# awaiting across the border
# ---------------------------------------------------------------------------
def _format_exception(exc):
    """the traceback of an exception as text: the message of the error
    JavaScript gets when Python code it called raised"""
    return "".join(traceback.format_exception(exc))


def _then(awaitable, resolve, reject):
    """Settle a JavaScript promise with the outcome of a Python awaitable.

    JavaScript calls this when it awaits a Python coroutine / future / task
    (the `then` of its PyProxy, src/js/pyproxy.ts): `resolve` and `reject`
    are the two functions of a new JavaScript promise.
    """
    future = asyncio.ensure_future(awaitable)

    def done(finished):
        try:
            result = finished.result()
        except BaseException as err:
            reject(_format_exception(err))
            return
        # A Python object as result must outlive this call: without
        # create_proxy JavaScript would get a proxy that is destroyed when
        # `resolve` returns. (Values that are converted, like numbers and
        # strings, pass through unchanged.)
        resolve(pyjs_core.create_proxy(result, False))

    future.add_done_callback(done)


def _rejection_to_exception(err):
    """The exception for a rejected JS promise: a JSException, like for
    errors thrown by synchronous JS calls, also when the promise was rejected
    with something that is no Error."""
    if isinstance(err, JSProxy):
        return error_to_py(err)
    # e.g. reject("text"), reject(undefined): arrive as python values
    return JSException(err, message=f"promise rejected with {err!r}")


def _to_future(js_promise):
    """An asyncio future that gets the outcome of a JavaScript promise."""
    future = asyncio.Future()

    def on_fulfilled(value):
        future.set_result(value)

    def on_rejected(err):
        future.set_exception(_rejection_to_exception(err))

    # The two Python functions are passed as plain arguments: their proxies
    # live until the promise returned by `then` settles, which is after one
    # of them ran. Nothing to destroy by hand.
    # then(ok, err), not then(ok).catch(err): an exception in `on_fulfilled`
    # must not end up in `on_rejected`.
    js_promise.then(on_fulfilled, on_rejected)
    return future


def _await_js(js_promise):
    """`await js_promise`: what the core calls for the `__await__` of a
    JSProxy of a promise (or any object with a `then` method)"""
    return _to_future(js_promise).__await__()


# ---------------------------------------------------------------------------
# emscripten main loop / animation frames
# ---------------------------------------------------------------------------
class _CallbackEntryPoint:
    """calls the user's main loop callback with the time since the last call"""

    def __init__(self, py_callback):
        self._py_callback = py_callback
        self._last_time = time.time()

    def __call__(self):
        t = time.time()
        dt = t - self._last_time
        self._last_time = t
        self._py_callback(dt)


_callback_entry_point = None


def set_main_loop_callback(py_callback, fps=0):
    """Call ``py_callback(dt)`` repeatedly from the emscripten main loop
    (`fps` 0: once per browser animation frame)."""
    global _callback_entry_point
    if _callback_entry_point is not None:
        # show a warning if the callback is already set
        warnings.warn(
            """ A main loop callback is already set.
            This will be replaced by the new callback,
            use cancel_main_loop before setting a new callback to avoid this warning
            """,
            UserWarning,
        )

        cancel_main_loop()

    _callback_entry_point = _CallbackEntryPoint(py_callback)

    pyjs_core._set_main_loop_callback(_callback_entry_point, int(fps))


def cancel_main_loop():
    """Cancel the main loop callback."""
    global _callback_entry_point
    if _callback_entry_point is not None:
        pyjs_core._cancel_main_loop()
        pyjs_core._set_noop_main_loop()
        _callback_entry_point = None
    else:
        warnings.warn("No main loop callback is set to cancel.", UserWarning)


class AnimationFrameLoop:
    """Handle of a loop started by `request_animation_frame_loop`."""

    def __init__(self, callback):
        self._callback = callback
        self._running = True

    @property
    def running(self) -> bool:
        """True until the loop stopped (callback returned falsy, raised, or `cancel`)."""
        return self._running

    def cancel(self):
        """Stop the loop before the next frame."""
        self._running = False

    def _tick(self, time_ms):
        # one frame: called by the C side, returns whether to continue
        if not self._running:
            return False
        try:
            keep_running = bool(self._callback(time_ms))
        except BaseException:
            self._running = False
            raise
        if not keep_running:
            self._running = False
        return keep_running


def request_animation_frame_loop(callback) -> AnimationFrameLoop:
    """Call `callback(time_ms)` once per browser animation frame.

    Uses `emscripten_request_animation_frame_loop` (`requestAnimationFrame`).
    The loop runs while `callback` returns something truthy; it stops when it
    returns something falsy, raises (the exception is printed), or the returned
    handle's `cancel()` is called. Each frame is a synchronous call from JS
    into Python, like the asyncio task steps.

    Args:
        callback: `callback(time_ms: float) -> bool`.

    Returns:
        an `AnimationFrameLoop` handle (`running`, `cancel()`).
    """
    loop = AnimationFrameLoop(callback)
    pyjs_core._request_animation_frame_loop(loop._tick)
    return loop


def set_canvas(canvas) -> None:
    """Make `canvas` the target of emscripten's GL / SDL / html5 code.

    Sets `Module.canvas` (used by SDL2) and registers it as `"#canvas"` (used by
    `emscripten_webgl_create_context("#canvas", ...)` and html5 event
    functions), so C / C++ code in extension modules renders into it.

    Args:
        canvas: a JS `HTMLCanvasElement` (main thread) or `OffscreenCanvas`.
    """
    _module._set_canvas(canvas)


# ---------------------------------------------------------------------------
# JSPI: blocking on a promise
# ---------------------------------------------------------------------------
def jspi_enabled() -> bool:
    """Whether JSPI (JavaScript Promise Integration) is used: the browser supports
    it (``WebAssembly.Suspending`` / ``WebAssembly.promising``) and it was not
    switched off. Without JSPI, `run_sync` is not available."""
    return bool(_module._jspi_enabled())


def _disable_jspi():
    """Switch JSPI off at runtime: pyjs then behaves like in a browser without
    JSPI (used by the tests to run the same build with and without JSPI)."""
    _module._jspi_disable()


def can_run_sync() -> bool:
    """Whether `run_sync` can be used here.

    True if JSPI is used (see `jspi_enabled`) and the current Python code was
    entered from JavaScript in a way that allows suspending: e.g. a step of an
    asyncio task (the event loop enters with a promising call), but not a
    plain synchronous callback (an event handler, `runPython`, ...).
    Only one Python call stack can be suspended at a time, so this is False
    while another `run_sync` is waiting.
    """
    return bool(_module._jspi_can_run_sync())


def _run_sync_python_awaitable(awaitable):
    """`run_sync` for a Python awaitable. Only a JavaScript promise can
    suspend the stack, so one is made that settles when the awaitable is
    done. Result and exception stay in Python: the promise only says "done"."""
    future = asyncio.ensure_future(awaitable)

    def executor(resolve, reject):
        future.add_done_callback(lambda f: resolve(None))

    # (the executor is called once, by the Promise constructor)
    _run_sync_js(_js.Promise.new(create_once_callable(executor)))
    return future.result()


def _run_sync_js(js_promise):
    # while this stack is suspended the event loop runs other tasks: asyncio
    # only allows one "current task" (per thread), so leave / re-enter it
    from asyncio import tasks as _tasks

    loop = asyncio.events._get_running_loop()
    task = asyncio.current_task(loop) if loop is not None else None
    if task is not None:
        _tasks._leave_task(loop, task)
    try:
        # suspend inside a copy of the current context: python code entered
        # while this stack is suspended (e.g. a kernel handling the next
        # message) would otherwise write its ContextVars into this task's context
        return contextvars.copy_context().run(pyjs_core.run_sync, js_promise)
    finally:
        if task is not None:
            _tasks._enter_task(loop, task)


def run_sync(awaitable):
    """Block until `awaitable` is done and return its result (JSPI only).

    `awaitable` is a JavaScript promise (or thenable) or a Python awaitable.
    The WebAssembly stack is suspended (JavaScript Promise Integration) until it
    settles: the browser event loop keeps running in the meantime.
    A rejected promise raises a `JSException`.
    Requires `can_run_sync()`, raises a ``RuntimeError`` otherwise.

    Example:
    ```python
    import js
    import pyjs

    def page_status():
        # a plain (sync) function waiting for a JavaScript promise
        response = pyjs.run_sync(js.fetch(js.location.href))
        return response.status

    page_status()  # 200
    ```
    """
    if not jspi_enabled():
        raise RuntimeError(
            "run_sync requires JSPI (WebAssembly.Suspending / WebAssembly.promising), "
            "which this browser does not support"
        )
    if not can_run_sync():
        raise RuntimeError(
            "run_sync cannot be used here: python was not entered via a "
            "promising call (e.g. it runs in a synchronous JavaScript callback) "
            "or another run_sync is already waiting"
        )
    if not isinstance(awaitable, JSProxy):
        return _run_sync_python_awaitable(awaitable)
    return _run_sync_js(awaitable)
