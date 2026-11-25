"""pyjs: use JavaScript from Python and Python from JavaScript.

The API follows PEP 818 and pyodide. The pieces:

* `pyjs_core` (C++, builtin module): the `JSProxy` type and the conversion of
  values. Everything else is built on it in Python.
* `ffi`: proxies (`create_proxy`, `create_once_callable`, `jsnull`, ...).
* `_proxy_types`: the methods of proxies of arrays, maps, generators, ...
  (`JSArray`, `JSMap`, ...; public through `ffi`).
* `convert`: deep copies between the languages (`to_py`, `to_js`).
* `error_handling`: JavaScript errors as Python exceptions (`JSException`).
* `code`: `run_js`, `eval_code`.
* `core`: awaiting, the main loop, `run_sync`.
* `webloop`: the asyncio event loop on top of the browser's.
* `_modules`: the names `js`, `jstypes`, `pyodide`.
* `_mocks`: stand-ins for stdlib modules that cannot exist in a browser.

Everything public is available directly: ``pyjs.create_proxy``,
``pyjs.to_js``, ``pyjs.run_sync``, ...
"""

import pyjs_core
from pyjs_core import JSProxy

from . import _proxy_types, code, ffi
from .ffi import *
from .error_handling import *
from .convert import *
from .convert import _to_py_with_converter
from .code import *
from .core import *
from .core import _await_js, _disable_jspi, _format_exception, _schedule_coroutine, _then
from .error_handling import error_to_py_and_raise

# Tell the core which Python objects to use (it cannot import this package:
# it is the other way round).
pyjs_core.set_hooks(
    # raises the exception for a value thrown by JavaScript
    error_to_py_and_raise,
    # the text of a Python exception, for the error JavaScript gets
    _format_exception,
    # `await js_promise`
    _await_js,
    # what JavaScript's null is in Python
    jsnull,
    # what a JavaScript BigInt is in Python
    JSBigInt,
    # proxy.to_py(default_converter=...): the step by step conversion
    _to_py_with_converter,
    # the classes with the extra methods of array / map / generator / ...
    # proxies
    _proxy_types.mixins,
    # starts the coroutine of an `async def` function JavaScript called
    _schedule_coroutine,
    # what a JavaScript Error object is in Python
    JSException,
)

#: JavaScript's global scope (``pyjs.js.document``); the same as ``import js``
js = pyjs_core.global_this()
#: the emscripten Module object of this runtime
_module = pyjs_core.module()
pyjs_core._module = _module

from . import _modules  # noqa: E402

_modules.install()

# (after `js` is importable: the event loop uses it)
from .webloop import *  # noqa: E402

#: False under node
IN_BROWSER = not _module._IS_NODE

# stand-ins for standard library modules that cannot exist in a browser
from . import _mocks  # noqa: E402

_mocks.install()
