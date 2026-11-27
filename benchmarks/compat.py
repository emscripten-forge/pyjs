"""The few FFI functions the benchmarks use, for pyjs and for pyodide.

The same benchmarks run on a pyjs page and on a pyodide page (the reference
pyjs is compared with): `RUNTIME` says which one this is. pyjs follows
pyodide's API, so almost everything is the same import from a different
module.
"""

try:
    import pyjs

    RUNTIME = "pyjs"
except ImportError:
    RUNTIME = "pyodide"

# JavaScript's global scope
import js  # noqa: E402, F401

if RUNTIME == "pyjs":
    from pyjs import buffer_to_js_typed_array, create_once_callable, create_proxy, to_js  # noqa: F401
    from pyjs import can_run_sync, run_sync  # noqa: F401
else:
    from pyodide.ffi import create_once_callable, create_proxy, to_js  # noqa: F401
    from pyodide.ffi import can_run_sync, run_sync  # noqa: F401

    # pyodide has no counterpart with a `view` option
    buffer_to_js_typed_array = None


def new(cls, *args):
    """`new cls(...args)`"""
    return cls.new(*args)


def to_py(js_val):
    """deep conversion of a JS value"""
    return js_val.to_py()
