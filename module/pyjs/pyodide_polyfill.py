from typing import Any
from .convert_py_to_js import to_js
from .error_handling import JsException
from .core import can_run_sync, run_sync
import sys
import types

def install_pyodide_polyfill():
    # Expose a small pyodide polyfill
    def _pyodide__getattr__(name: str) -> Any:
        if name == "to_js":
            return to_js

        raise AttributeError(
            "This is not the real Pyodide. We are providing a small Pyodide polyfill for conveniance."
            "If you are missing an important Pyodide feature, please open an issue in https://github.com/emscripten-forge/pyjs/issues"
        )

    pyodide = sys.modules["pyodide"] = types.ModuleType("pyodide")
    pyodide.ffi = sys.modules["pyodide.ffi"] = types.ModuleType("ffi")
    pyodide.ffi.JsException = JsException
    pyodide.ffi.JsArray = object
    pyodide.ffi.JsProxy = object
    # urllib3 (contrib/emscripten) uses fetch + run_sync when can_run_sync()
    pyodide.ffi.can_run_sync = can_run_sync
    pyodide.ffi.run_sync = run_sync
    pyodide.code = sys.modules["pyodide.code"] = types.ModuleType("code")
    pyodide.code.run_js = _run_js
    pyodide.__getattr__ = _pyodide__getattr__
    pyodide.ffi.__getattr__ = _pyodide__getattr__
    pyodide.code.__getattr__ = _pyodide__getattr__


def _run_js(code: str) -> Any:
    """`pyodide.code.run_js`: evaluate JS `code` in the global scope (indirect
    eval) and return the value of its last expression."""
    import pyjs_core
    return pyjs_core.js.eval(code)



install_pyodide_polyfill()
del install_pyodide_polyfill