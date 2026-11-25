"""What pyjs has beyond the foreign function interface (`pyjs.ffi`):
awaiting across the two languages, the emscripten main loop / animation
frames, and blocking on a promise (`run_sync`, JSPI)."""

import asyncio
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
    JavaScript gets when Python code it called raised. The frames of pyjs'
    own code running it (runPython -> pyjs/code.py) are left out at the
    start: the traceback begins with the user's code."""
    tb = exc.__traceback__
    while tb is not None and tb.tb_next is not None and tb.tb_frame.f_code.co_filename.endswith("pyjs/code.py"):
        tb = tb.tb_next
    return "".join(traceback.format_exception(type(exc), exc, tb))


def _then(awaitable, settle):
    """Settle a JavaScript promise with the outcome of a Python awaitable.

    JavaScript calls this when it awaits a Python coroutine / future / task
    (the `then` of its PyProxy, src/js/pyproxy.ts). When the awaitable is
    done, `settle` (a JavaScript function) is called with the `result`
    method of the finished future. JavaScript calls that method: it returns
    the result or raises the exception, which JavaScript turns into a
    resolved or rejected promise.
    """
    future = asyncio.ensure_future(awaitable)
    future.add_done_callback(lambda finished: settle(finished.result))


def _schedule_coroutine(coroutine):
    """Start a coroutine as asyncio task. The core calls this when a Python
    function called from JavaScript returned a coroutine (an `async def`
    function was called): JavaScript expects the function to run, and gets
    the task to await."""
    return asyncio.ensure_future(_run_to_the_end(coroutine))


async def _run_to_the_end(coroutine):
    """the result of `coroutine`; if that is a coroutine again (an `async
    def` function that returns `other()` without awaiting it), it runs too,
    as JavaScript's async functions resolve returned promises (pyodide does
    the same)"""
    result = await coroutine
    while asyncio.iscoroutine(result):
        result = await result
    return result


# a step of a JavaScript iterator
_step_object = _js.Function("done", "value", "return {done: done, value: value};")


def _generator_step(generator, method, argument):
    """The JavaScript generator methods of the proxy of a Python generator
    (src/js/pyproxy.ts): `next(value)` is python's send, `throw(error)` its
    throw, `return(value)` its close. The result is the step object
    ``{done, value}`` JavaScript expects; the value of a finished generator
    is its return value."""
    try:
        if method == "next":
            value = generator.send(argument)
        elif method == "throw":
            # (a JavaScript Error arrives as JSException; anything else
            # thrown is wrapped in one)
            if not isinstance(argument, BaseException):
                argument = JSException(argument)
            value = generator.throw(argument)
        else:
            generator.close()
            return _step_object(True, _lasting(argument))
    except StopIteration as stop:
        return _step_object(True, _lasting(stop.value))
    return _step_object(False, _lasting(value))


def _lasting(value):
    """a value that is stored in a JavaScript object: a Python object needs a
    lasting proxy (see create_proxy); converted values are returned as they
    are"""
    return pyjs_core.create_proxy(value, False)


def _rejection_to_exception(err):
    """The exception for a rejected JS promise: a JSException, like for
    errors thrown by synchronous JS calls, also when the promise was rejected
    with something that is no Error."""
    if isinstance(err, (JSProxy, JSException)):
        if _module._is_python_error(err):
            # A Python exception that travelled through JavaScript (python
            # awaits a promise that python code rejected, e.g. the promise
            # of runPythonAsync): the original exception, not a JSException
            # wrapping its JavaScript stand-in. Throwing the stand-in from
            # JavaScript raises the exception inside it.
            try:
                _module._throw(err)
            except BaseException as original:
                return original
        if isinstance(err, JSException):
            # (a rejection with an Error object: it arrived as JSException)
            return err
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
    # (the proxy type is chosen when the object first reaches python: its
    # `then` may have been removed since)
    if not callable(getattr(js_promise, "then", None)):
        raise TypeError(f"object {js_promise!r} can't be used in 'await' expression")
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
    Any number of Python call stacks can be suspended in `run_sync` at the
    same time; they resume in any order.
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
    # While this stack is suspended, other Python code runs (other asyncio
    # tasks, event handlers, other suspended stacks that resume). The C side
    # takes this stack's part of the thread state away meanwhile (frames,
    # exception state, contextvars context, asyncio's current task) and puts
    # it back when it resumes: see src/stack_switching.c.
    return pyjs_core.run_sync(js_promise)


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
            "promising call (e.g. it runs in a synchronous JavaScript callback)"
        )
    if not isinstance(awaitable, JSProxy):
        return _run_sync_python_awaitable(awaitable)
    return _run_sync_js(awaitable)
