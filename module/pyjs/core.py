import contextlib
import json
import sys
import types
from typing import Any
import ast
import inspect
import pyjs_core
from pyjs_core import JsValue, js_array, js_py_object
import warnings
import time

def _install_submodules():
    def _js_mod__getattr__(name: str) -> Any:
        ret = pyjs_core.internal.global_property(name)
        if ret is None:
            raise AttributeError(f"has no attribute {name}")
        return ret

    js = sys.modules["pyjs.js"] = sys.modules["js"] = sys.modules["pyjs_core.js"] = types.ModuleType("js")
    js.__getattr__ = _js_mod__getattr__
    pyjs_core.js = js

    def _module_mod__getattr__(name: str) -> Any:
        ret = pyjs_core.internal.module_property(name)
        if pyjs_core.internal.is_undefined_or_null(ret):
            raise AttributeError(f"has no attribute {name}")
        return ret

    _module = sys.modules["pyjs_core._module"] = types.ModuleType("_module")
    _module.__getattr__ = _module_mod__getattr__
    pyjs_core._module = _module


_install_submodules()
del _install_submodules




def new(cls_, *args):
    """ Create a new instance of a JavaScript class.

    This function is a wrapper around the `new` operator in JavaScript.
    
    Args:
        cls_ (JsValue): The JavaScript class to create an instance of
        *args (Any): The arguments to pass to the constructor of the JavaScript class
    """
    return pyjs_core._module._new(cls_, *args)

# todo deprecate
def async_import_javascript(path):
    return pyjs_core._module._async_import_javascript(path)


# TODO make private
def type_str(x):
    return pyjs_core.internal.type_str(x)


def create_callable(py_function):
    '''Create a JavaScript callable from a Python function.

    Args:
        py_function (Callable): The Python function to create a JavaScript callable from.

    Example:
    ```python
    def py_function(x, y):
        return x + y

    js_callable, js_py_object = pyjs.create_callable(py_function)
    
    # this function can be passed to JavaScript.
    # lets create some JavaScript code to test it
    higher_order_function = pyjs.js.Function("f", "x", "y", "z", """
        return z * f(x, y);
    """)
    
    # call the higher order JavaScript function
    # with py_function wrapped as a JavaScript callable
    result = higher_order_function(js_callable, 1, 2, 3)
    assert result == 9

    js_py_object.delete()
    ```

    Returns:
        callable: The JavaScript callable
        js_py_object: this object needs to be deleted after the callable is no longer needed
    '''    
    _js_py_object = js_py_object(py_function)
    return _js_py_object["py_call"].bind(_js_py_object), _js_py_object


@contextlib.contextmanager
def callable_context(py_function):
    ''' Create a JavaScript callable from a Python function and delete it when the context is exited.

    See `create_callable` for more information.
    
    Args:
        py_function (Callable): The Python function to create a JavaScript callable from.
    
    Example:

    ```python
    def py_function(x, y):
        return x + y

    with pyjs.callable_context(py_function) as js_function:
        # js_function is a JavaScript callable and could be
        # passed to and called from JavaScript,
        # here we just call it from Python
        print(js_function(1,2))
    ```
    '''

    
    cb, handle = create_callable(py_function)
    yield cb
    handle.delete()


# todo, deprecate
class AsOnceCallableMixin(object):
    def __init__(self):
        self._once_callable = create_once_callable(self)

    def as_once_callable(self):
        return self._once_callable


def promise(py_resolve_reject):
    """ Create a new JavaScript promise with a python callback to resolve or reject the promise.
    
    Args:
        py_resolve_reject (Callable): A Python function that takes two arguments, resolve and reject, which are both functions.
            The resolve function should be called with the result of the promise and the reject function should be called with an error.
    
    Example:
    ```python
    import asyncio
    import pyjs
    def f(resolve, reject):
        async def task():
            try:
                print("start task")
                await asyncio.sleep(1)
                print("end task")
                # resolve when everything is done
                resolve()
            except:
                # reject the promise in case of an error
                reject()
        asyncio.create_task(task())

    js_promise = pyjs.promise(f)
    print("await the js promise from python")
    await js_promise
    print("the wait has an end")
    print(js_promise)
    ```
    """

    return pyjs_core.js.Promise.new(create_once_callable(py_resolve_reject))


def create_once_callable(py_function):
    """Create a JavaScript callable from a Python function that can only be called once.
    
    Since this function can only be called once, it will be deleted after the first call.
    Therefore no manual deletion is necessary.
    See `create_callable` for more information.

    Args:
        py_function (Callable): The Python function to create a JavaScript callable from.

    Returns:
        callable: The JavaScript callable
    
    Example:
    ```python

    def py_function(x, y):
        return x + y

    js_function = pyjs.create_once_callable(py_function)
    print(js_function(1,2)) # this will print 3

    # the following will raise an error
    try:
        print(js_function(1,2))
    except pyjs.JsException as e:
        print("error:", e.message)
    ```
    """
    
    js_py_function = JsValue(py_function)
    once_callable = pyjs_core._module._create_once_callable(js_py_function)
    return once_callable


def _make_js_args(args):
    js_array_args = js_array()
    is_generated_proxy = js_array()
    for arg in args:
        js_arg, is_proxy = pyjs_core.internal.implicit_py_to_js(arg)
        pyjs_core.internal.val_call(js_array_args, "push", js_arg)
        pyjs_core.internal.val_call(is_generated_proxy, "push", JsValue(is_proxy))
    return (js_array_args, is_generated_proxy)


def apply(js_function, args):
    '''Call a JavaScript function with the given arguments.

    Args:
        js_function (JsValue): The JavaScript function to call
        args (List): The arguments to pass to the JavaScript function
    
    Returns:
        Any: The result of the JavaScript function
    
    Example:
    ```python

    # create a JavaScript function on the fly
    js_function = pyjs.js.Function("x", "y", """
        return x + y;
    """)
    result = pyjs.apply(js_function, [1, 2])
    assert result == 3
    ```
    '''
    js_array_args, is_generated_proxy = _make_js_args(args)
    ret, meta = pyjs_core.internal.apply_try_catch(js_function, js_array_args, is_generated_proxy)
    return ret


# deprecated
def japply(js_function, args):
    sargs = json.dumps(args)
    ret, meta = pyjs_core.internal.japply_try_catch(js_function, sargs)
    return ret

# deprecated
def gapply(js_function, args, jin=True, jout=True):
    if jin:
        args = json.dumps(args)
        is_generated_proxy = [False] * len(args)
    else:
        args, is_generated_proxy = _make_js_args(args)
    ret = pyjs_core.internal.gapply_try_catch(js_function, args, is_generated_proxy, jin, jout)
    if jout:
        if ret == "":
            return None
        else:
            return json.loads(ret)
    else:
        return ret


# move to internal
def exec_eval(script, globals=None, locals=None):
    """Execute a script and return the value of the last expression"""
    stmts = list(ast.iter_child_nodes(ast.parse(script)))
    if not stmts:
        return None
    if isinstance(stmts[-1], ast.Expr):
        # the last one is an expression and we will try to return the results
        # so we first execute the previous statements
        if len(stmts) > 1:
            exec(
                compile(
                    ast.Module(body=stmts[:-1], type_ignores=[]),
                    filename="<ast>",
                    mode="exec",
                ),
                globals,
                locals,
            )
        # then we eval the last one
        return eval(
            compile(
                ast.Expression(body=stmts[-1].value), filename="<ast>", mode="eval"
            ),
            globals,
            locals,
        )
    else:
        # otherwise we just execute the entire code
        return exec(script, globals, locals)

async def async_exec_eval(stmts, globals=None, locals=None):
    """Execute a script which may use top level `await`, return the value of
    the last expression (like `exec_eval`).

    The script runs with module level semantics (`PyCF_ALLOW_TOP_LEVEL_AWAIT`,
    like the asyncio REPL / IPython): assignments go to `globals`, each
    statement runs exactly once.
    """
    flags = ast.PyCF_ALLOW_TOP_LEVEL_AWAIT

    async def run(code):
        result = eval(code, globals, locals)
        if code.co_flags & inspect.CO_COROUTINE:
            result = await result
        return result

    body = ast.parse(stmts).body
    if not body:
        return None
    if isinstance(body[-1], ast.Expr):
        if len(body) > 1:
            module = ast.Module(body=body[:-1], type_ignores=[])
            await run(compile(module, filename="<ast>", mode="exec", flags=flags))
        expression = ast.Expression(body=body[-1].value)
        return await run(compile(expression, filename="<ast>", mode="eval", flags=flags))
    module = ast.Module(body=body, type_ignores=[])
    await run(compile(module, filename="<ast>", mode="exec", flags=flags))
    return None


class _CallbackEntryPoint:
    def __init__(self, py_callback):
        self._py_callback = py_callback
        self._last_time = time.time()
    def __call__(self):
        t =  time.time()
        dt = t - self._last_time
        self._last_time = t
        self._py_callback(dt)

_callback_entry_point = None


def set_main_loop_callback(py_callback, fps=0):

    global  _callback_entry_point
    if _callback_entry_point is not None:
        # show a warning if the callback is already set
        warnings.warn(""" A main loop callback is already set. 
            This will be replaced by the new callback,
            use cancel_main_loop before setting a new callback to avoid this warning
            """,
            UserWarning)
        
        cancel_main_loop()
    
    _callback_entry_point = _CallbackEntryPoint(py_callback)

    pyjs_core._set_main_loop_callback(
        _callback_entry_point,
        int(fps)
    )
   

def cancel_main_loop():
    """Cancel the main loop callback."""
    global _callback_entry_point
    if _callback_entry_point is not None:
        pyjs_core._cancel_main_loop()
        pyjs_core._set_noop_main_loop()
        _callback_entry_point = None
    else:
        warnings.warn("No main loop callback is set to cancel.", UserWarning)

def jspi_enabled() -> bool:
    """Whether JSPI (JavaScript Promise Integration) is used: the browser supports
    it (``WebAssembly.Suspending`` / ``WebAssembly.promising``) and it was not
    switched off. Without JSPI, `run_sync` is not available."""
    return bool(pyjs_core.internal.module_property("_jspi_enabled")())


def _disable_jspi():
    """Switch JSPI off at runtime: pyjs then behaves like in a browser without
    JSPI (used by the tests to run the same build with and without JSPI)."""
    pyjs_core.internal.module_property("_jspi_disable")()


def can_run_sync() -> bool:
    """Whether `run_sync` can be used here.

    True if JSPI is used (see `jspi_enabled`) and the current Python code was
    entered from JavaScript in a way that allows suspending: e.g. a step of an
    asyncio task (the event loop enters via ``py_apply_promising``), but not a
    plain synchronous callback (event handler, `create_callable`, `pyjs.exec`, ...).
    Only one Python call stack can be suspended at a time, so this is False
    while another `run_sync` is waiting.
    """
    if not jspi_enabled():
        return False
    return bool(pyjs_core.internal.module_property("_jspi_can_run_sync")())


def _run_sync_python_awaitable(awaitable):
    # result / exception stay in python, the js promise only signals "done"
    import asyncio

    future = asyncio.ensure_future(awaitable)

    def executor(resolve, reject):
        future.add_done_callback(lambda f: resolve(None))

    _run_sync_js(promise(executor))
    return future.result()


def _run_sync_js(js_promise):
    # while this stack is suspended the event loop runs other tasks: asyncio
    # only allows one "current task" (per thread), so leave / re-enter it
    import asyncio
    from asyncio import tasks as _tasks

    loop = asyncio.events._get_running_loop()
    task = asyncio.current_task(loop) if loop is not None else None
    if task is not None:
        _tasks._leave_task(loop, task)
    try:
        ret, _ = pyjs_core.internal.run_sync(js_promise)
    finally:
        if task is not None:
            _tasks._enter_task(loop, task)
    return ret


def run_sync(awaitable):
    """Block until `awaitable` is done and return its result (JSPI only).

    `awaitable` is a JavaScript promise (or thenable) or a Python awaitable.
    The WebAssembly stack is suspended (JavaScript Promise Integration) until it
    settles: the browser event loop keeps running in the meantime.
    A rejected promise raises the corresponding `JsException`.
    Requires `can_run_sync()`, raises a ``RuntimeError`` otherwise.

    Example:
    ```python
    import pyjs

    def page_status():
        # a plain (sync) function waiting for a JavaScript promise
        response = pyjs.run_sync(pyjs.js.fetch(pyjs.js.location.href))
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
    if not isinstance(awaitable, JsValue):
        return _run_sync_python_awaitable(awaitable)
    return _run_sync_js(awaitable)
