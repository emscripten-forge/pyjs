"""The C++ core of pyjs (a builtin module of the runtime, see src/module.cpp).

Only the parts users meet are described here; everything else is used by the
`pyjs` package."""

from typing import Any


class JSProxy:
    """A JavaScript value in Python (any object or function; numbers, strings,
    booleans, ``undefined`` and ``null`` become Python values instead).

    Attribute access, ``proxy[key]``, calls, ``len``, ``in``, iteration,
    ``await`` and comparisons go to JavaScript. Depending on what the
    JavaScript object can do, the proxy also has the methods of `JSArray`,
    `JSMap`, `JSCallable`, `JSPromise`, ... (``isinstance`` works with those
    classes).
    """

    @property
    def typeof(self) -> str:
        """the JavaScript ``typeof`` of the object, e.g. ``"object"``"""
        ...

    @property
    def js_id(self) -> int:
        """an int, equal for two proxies exactly if they are the same JavaScript object"""
        ...

    def to_py(self, *, depth: int = -1, default_converter: Any = None) -> Any:
        """A deep copy as Python objects: Array -> list, Map and plain Object
        -> dict, Set -> set, typed array / ArrayBuffer -> memoryview. See
        `pyjs.to_py`."""
        ...

    def new(self, *args: Any, **kwargs: Any) -> Any:
        """JavaScript's ``new proxy(*args)`` (only for functions / classes)."""
        ...


def global_this() -> JSProxy:
    """JavaScript's ``globalThis`` (the same as `pyjs.js`)"""
    ...


def module() -> JSProxy:
    """the emscripten Module of this runtime"""
    ...
