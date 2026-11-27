"""The foreign function interface between Python and JavaScript.

The names follow PEP 818 (which proposes this API for the standard library as
``jstypes.ffi``); ``import pyjs`` also makes this module available as
``jstypes.ffi`` and, for code written for pyodide, as ``pyodide.ffi``.

The two kinds of proxies:

* A `JSProxy` is a *Python* object that stands for a *JavaScript* object. You
  get one whenever a JavaScript object reaches Python (``js.document``, the
  result of calling a JavaScript function, ...). Attribute access, calls,
  ``len()``, iteration etc. are forwarded to the JavaScript object.
* A PyProxy is the reverse: a *JavaScript* object that stands for a *Python*
  object. JavaScript gets one whenever a Python object is passed to it.

What is converted instead of proxied (in both directions): ``None`` /
``undefined``, `jsnull` / ``null``, ``bool``, ``int`` / ``float`` / numbers
and ``str`` / strings.
"""

import pyjs_core
from pyjs_core import JSProxy

from . import _proxy_types
from ._proxy_types import *  # noqa: F401,F403  (JSArray, JSMap, ...)

__all__ = [
    *_proxy_types.__all__,
    "JSProxy",
    "JSNull",
    "jsnull",
    "JSBigInt",
    "create_proxy",
    "create_once_callable",
    "destroy_proxies",
]


class JSNull:
    """The type of `jsnull`, the Python value of JavaScript's ``null``.

    JavaScript has two "nothing" values, ``undefined`` and ``null``. Python has
    one, ``None``, which stands for ``undefined``. ``null`` is this separate
    object, so that both survive a round trip. Like ``None`` it is false in a
    condition and there is only one of it.
    """

    _instance = None

    def __new__(cls):
        # always the same object
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self):
        return False

    def __repr__(self):
        return "jsnull"


#: JavaScript's ``null``
jsnull = JSNull()


class JSBigInt(int):
    """An ``int`` that is always converted to a JavaScript ``BigInt``.

    A plain ``int`` becomes a JavaScript number when that can hold it exactly
    and a ``BigInt`` only when it is too large. Use this type where JavaScript
    requires a ``BigInt`` also for small values. A ``BigInt`` coming from
    JavaScript arrives as this type. Arithmetic on it gives a `JSBigInt`
    again (``JSBigInt(2) + 1`` is ``JSBigInt(3)``), as in JavaScript.
    """


# json.dumps(jsnull) is "null", like None: jsnull stands for JavaScript's null,
# which is what JSON's null is. (json has no way to register a type: its
# encoder's fallback for unknown objects is extended.)
import json as _json  # noqa: E402

_json_default = _json.JSONEncoder.default


def _json_default_with_jsnull(encoder, o):
    if o is jsnull:
        return None
    return _json_default(encoder, o)


_json.JSONEncoder.default = _json_default_with_jsnull


def _keeps_bigint(name):
    """the `int` operation `name`, with an int result turned into a JSBigInt
    (`int` itself returns a plain int, also for subclasses)"""
    int_operation = getattr(int, name)

    def operation(self, *args):
        result = int_operation(self, *args)
        # (not for bool, float or NotImplemented results)
        return JSBigInt(result) if type(result) is int else result

    operation.__name__ = name
    return operation


for _name in (
    "add sub mul floordiv mod pow lshift rshift and or xor "
    "radd rsub rmul rfloordiv rmod rpow rlshift rrshift rand ror rxor "
    "neg pos abs invert"
).split():
    setattr(JSBigInt, f"__{_name}__", _keeps_bigint(f"__{_name}__"))


def create_proxy(obj, *, roundtrip=True):
    """Give JavaScript a lasting reference to the Python object `obj`.

    A Python object passed to a JavaScript function is normally only usable by
    JavaScript *during that call* (its proxy is destroyed when the call
    returns, so that nothing leaks). When JavaScript has to keep it (an event
    handler, a callback called later, a value stored in a JavaScript object)
    pass ``create_proxy(obj)`` instead.

    The result must be released with its ``destroy()`` method once JavaScript
    does not need it any more; `obj` cannot be freed before that.

    What the result is: always a `JSDoubleProxy`. The lasting reference is a
    JavaScript object (a PyProxy of `obj`), and Python can only hold a
    JavaScript object through a JSProxy: so a proxy (JSProxy) of a proxy
    (PyProxy) of `obj`. It is what you pass to JavaScript (JavaScript gets
    the PyProxy) and what you call ``destroy()`` on. See `JSDoubleProxy`.

    `roundtrip`: what Python gets when this PyProxy comes BACK from
    JavaScript later, e.g. read from an Array it was stored in, or passed as
    argument to a Python function:

    - ``roundtrip=True`` (the default, as in pyodide): the JSDoubleProxy
      again. So code that finds the proxy again can still destroy it;
      ``proxy.unwrap()`` gives `obj`.
    - ``roundtrip=False``: `obj` itself, as for any other PyProxy coming
      back. Convenient when Python only wants to use the object, but that
      value cannot destroy the PyProxy (keep the JSDoubleProxy for that).

    ```python
    import js
    from pyjs import create_proxy

    data = [1, 2]
    arr = js.Array.new()

    # roundtrip=True (the default): a JSDoubleProxy comes back
    p = create_proxy(data)
    arr.push(p)
    back = arr[0]                 # a JSDoubleProxy of the same PyProxy as p
    assert back.unwrap() is data
    back.destroy()                # (the same as p.destroy())

    # roundtrip=False: the object itself comes back
    p = create_proxy(data, roundtrip=False)
    arr[0] = p
    assert arr[0] is data
    p.destroy()                   # only p can destroy it
    ```

    Example:
    ```python
    import js
    from pyjs import create_proxy

    def on_click(event):
        print("clicked")

    button = js.document.createElement("button")
    handler = create_proxy(on_click)
    button.addEventListener("click", handler)
    button.click()                # prints "clicked"
    button.removeEventListener("click", handler)
    handler.destroy()
    ```
    """
    return pyjs_core.create_proxy(obj, True, roundtrip)


# Destroys the PyProxies stored in a JavaScript Array, inside JavaScript.
#
# Why not in Python: reading an item of the Array in Python does not give
# the PyProxy. A PyProxy that comes back to Python becomes the Python object
# it stands for (a list, a function, ...), and that object has no destroy().
# So the loop must run where the items are still PyProxies: in JavaScript.
_destroy_in_js = pyjs_core.global_this().Function("proxies", "for (const p of proxies) { p.destroy(); }")


def destroy_proxies(proxies):
    """Destroy every proxy of `proxies`. Two kinds of argument:

    - a Python list (any iterable) of `create_proxy` results: each is
      destroyed with its `destroy()`
    - a JavaScript Array, which Python sees as one JSProxy: the Array that
      `to_js(obj, pyproxies=arr)` filled with the PyProxies it created. Its
      items are destroyed in JavaScript (see `_destroy_in_js`).
    """
    if isinstance(proxies, JSProxy):
        # (the JSProxy of a JavaScript Array, not a single proxy)
        _destroy_in_js(proxies)
        return
    for proxy in proxies:
        proxy.destroy()


# Wraps a PyProxy `f` (JavaScript's stand-in for a Python callable) into a
# JavaScript function that calls it once and then releases it.
_once = pyjs_core.global_this().Function(
    "f",
    """
    let called = false;
    return function (...args) {
        if (called) {
            throw new Error("once_callable can only be called once");
        }
        called = true;
        try {
            return f(...args);
        } finally {
            f.destroy();
        }
    };
    """,
)


def create_once_callable(func):
    """A JavaScript function that calls the Python callable `func`, once.

    Like `create_proxy` for a callback that is called exactly one time (a
    timeout, a promise callback): the reference to `func` is released by that
    call, nothing has to be destroyed by hand. A second call raises an error.
    """
    return _once(pyjs_core.create_proxy(func))
