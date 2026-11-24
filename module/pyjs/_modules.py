"""The other names this package is importable under.

`import pyjs` (which the runtime always does when python starts) registers:

* ``js``: JavaScript's global scope. ``import js; js.document`` or
  ``from js import fetch``.
* ``jstypes``, ``jstypes.ffi``, ``jstypes.code``, ``jstypes.global_this``: the
  names PEP 818 proposes for the standard library. Code written against the
  PEP runs unchanged.
* ``pyodide``, ``pyodide.ffi``, ``pyodide.code``: so that code written for
  pyodide (urllib3, pyodide-http, ...) runs. This is not pyodide: only what
  pyjs has is there.

Nothing here is implemented twice: all of them are the objects of `pyjs`.
"""

import sys
import types

import pyjs_core
from pyjs_core import JSProxy

from . import code, convert, core, error_handling, ffi

# JavaScript's globalThis. A JSProxy, not a module: the import system accepts
# any object in sys.modules, and `js.document` then is a direct attribute
# access on the proxy.
global_this = pyjs_core.global_this()


def _module(name, **attributes):
    """a new module `name` with the given attributes, registered in sys.modules"""
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    sys.modules[name] = module
    return module


def install():
    """register all the names, see the module docstring"""
    sys.modules["js"] = global_this

    # PEP 818
    ffi_names = dict(
        JSProxy=JSProxy,
        JSNull=ffi.JSNull,
        jsnull=ffi.jsnull,
        JSBigInt=ffi.JSBigInt,
        JSException=error_handling.JSException,
        create_proxy=ffi.create_proxy,
        create_once_callable=ffi.create_once_callable,
        destroy_proxies=ffi.destroy_proxies,
        to_js=convert.to_js,
    )
    jstypes = _module("jstypes")
    jstypes.ffi = _module("jstypes.ffi", **ffi_names)
    jstypes.code = _module("jstypes.code", run_js=code.run_js)
    jstypes.global_this = sys.modules["jstypes.global_this"] = global_this

    # pyodide spells the types with a lower case s, and has more functions
    pyodide_names = dict(
        ffi_names,
        JsProxy=JSProxy,
        JsNull=ffi.JSNull,
        JsBigInt=ffi.JSBigInt,
        JsException=error_handling.JSException,
        ConversionError=convert.ConversionError,
        can_run_sync=core.can_run_sync,
        run_sync=core.run_sync,
        # (pyodide has one type per kind of JavaScript object)
        JsArray=JSProxy,
        JsCallable=JSProxy,
        JsMap=JSProxy,
        JsBuffer=JSProxy,
    )
    pyodide = _module("pyodide")
    pyodide.ffi = _module("pyodide.ffi", **pyodide_names)
    pyodide.code = _module(
        "pyodide.code",
        run_js=code.run_js,
        eval_code=code.eval_code,
        eval_code_async=code.eval_code_async,
    )
