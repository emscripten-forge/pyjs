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

__all__ = [
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
    JavaScript arrives as this type.
    """


def create_proxy(obj):
    """Give JavaScript a lasting reference to the Python object `obj`.

    A Python object passed to a JavaScript function is normally only usable by
    JavaScript *during that call* (its proxy is destroyed when the call
    returns, so that nothing leaks). When JavaScript has to keep it (an event
    handler, a callback called later, a value stored in a JavaScript object)
    pass ``create_proxy(obj)`` instead.

    The result must be released with its ``destroy()`` method once JavaScript
    does not need it any more; `obj` cannot be freed before that.

    Example:
    ```python
    handler = create_proxy(on_click)
    button.addEventListener("click", handler)
    ...
    button.removeEventListener("click", handler)
    handler.destroy()
    ```
    """
    return pyjs_core.create_proxy(obj)


def destroy_proxies(proxies):
    """Destroy every proxy of `proxies` (an iterable of `create_proxy` results)."""
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
