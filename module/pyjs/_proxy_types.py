"""The methods a `JSProxy` has on top of the basic operations, by kind of
JavaScript object: `append` for an Array, `keys` for a Map, `send` for a
generator, `to_bytes` for a typed array, ...

How this fits together. When a JavaScript object reaches Python, JavaScript
reports what the object can do as a set of flags (``JsFlag`` in
``src/slot.hpp``). The core creates one Python type per set of flags and
asks `mixins` (below) which of the classes of this module that type shall
inherit from. So a proxy of an Array is an instance of `JSProxy` *and* of
`JSArray`, and ``isinstance(proxy, JSArray)`` is the way to ask "is this an
Array?".

The classes have no data of their own (``__slots__ = ()``): the proxy is the
C object of the core, the classes only add methods to it.

The names and the behaviour follow PEP 818 and pyodide.
"""

import asyncio
import functools
from collections.abc import (
    ItemsView,
    KeysView,
    Mapping,
    MutableMapping,
    MutableSequence,
    Sequence,
    ValuesView,
)

import pyjs_core
from pyjs_core import JSProxy

from .error_handling import JSException

__all__ = [
    "JSDoubleProxy",
    "JSArray",
    "JSTypedArray",
    "JSBuffer",
    "JSMap",
    "JSMutableMap",
    "JSCallable",
    "JSPromise",
    "JSIterable",
    "JSIterator",
    "JSGenerator",
    "JSAsyncIterable",
    "JSAsyncIterator",
    "JSAsyncGenerator",
]

_js = pyjs_core.global_this()

# Calls the JavaScript method `name` of `obj`.
#
# Why not simply ``obj.name(...)``: a method of the classes below hides the
# JavaScript method of the same name (``proxy.pop`` is `JSArray.pop`, not
# Array.prototype.pop). The classes use this helper to reach the JavaScript
# method they stand in front of.
_method = _js.Function("obj", "name", "...args", "return obj[name](...args);")

# obj[Symbol.asyncIterator](): the async iterator of an async iterable (a
# symbol cannot be written as attribute name in Python)
_async_iterator = _js.Function("obj", "return obj[Symbol.asyncIterator]();")

# The flags (must be identical to JsFlag in src/slot.hpp)
_CALLABLE = 1 << 0
_ITERABLE = 1 << 3
_ITERATOR = 1 << 4
_AWAITABLE = 1 << 5
_GETITEM = 1 << 6
_SETITEM = 1 << 7
_ARRAY = 1 << 8
_BUFFER = 1 << 9
_MAP = 1 << 10
_GENERATOR = 1 << 11
_ASYNC_ITERABLE = 1 << 12
_ASYNC_ITERATOR = 1 << 13
_DOUBLE_PROXY = 1 << 15


_module = pyjs_core.module()


def _keep(item):
    """What to hand to JavaScript when it will STORE `item` (in an Array,
    ...). A Python object passed to a JavaScript function is normally only
    usable during that call; this gives a lasting reference instead (see
    `create_proxy`). Values that are converted (numbers, strings, JS
    objects) are returned as they are."""
    return pyjs_core.create_proxy(item, False)


class _Mixin:
    """Base of the classes of this module. They only describe proxies: there
    is nothing to create."""

    __slots__ = ()

    def __new__(cls, *args, **kwargs):
        raise TypeError(f"{cls.__name__} cannot be instantiated: proxies are created by JavaScript objects reaching Python")


# f.apply(this_, args): runs the JavaScript function `f` as method of `this_`
_apply_with_this = _js.Function("f", "this_", "...args", "return Reflect.apply(f, this_, args);")


class JSCallable(_Mixin):
    """A JavaScript function or class: ``proxy(...)`` calls it,
    ``proxy.new(...)`` is JavaScript's ``new proxy(...)``."""

    __slots__ = ()

    def __get__(self, instance, owner=None):
        # A JavaScript function stored as attribute of a Python class is a
        # method, like a Python function there: `instance.f(1)` runs it with
        # `this` = the instance (as pyodide does).
        if instance is None:
            return self
        return functools.partial(_apply_with_this, self, instance)


class JSPromise(_Mixin):
    """A JavaScript promise (anything with a ``then`` method): it can be
    awaited."""

    __slots__ = ()


class JSIterable(_Mixin):
    """A JavaScript object that can be iterated (``for x in proxy``)."""

    __slots__ = ()


class JSIterator(_Mixin):
    """A JavaScript iterator (``next(proxy)``)."""

    __slots__ = ()

    def send(self, value):
        """``next(value)`` of the iterator: the next value, StopIteration at
        the end (like a Python generator's send)."""
        return _step(_method(self, "next", _keep(value)))


class _Hidden:
    """A class attribute that makes the attribute `name` look missing.

    Used to hide JavaScript methods of the same name as a Python protocol
    method with another meaning: an Array has a `keys()` method, and Python
    code takes everything with `keys` for a mapping (``dict(js_array)`` would
    read the array as dict of index -> item)."""

    def __init__(self, name):
        self._name = name

    def __get__(self, instance, owner=None):
        raise AttributeError(self._name)


def _slice_indices(proxy, key):
    """the indices a slice selects in `proxy`, as a range"""
    return range(*key.indices(len(proxy)))


class JSDoubleProxy(_Mixin):
    """A Python object behind a JavaScript proxy behind a JSProxy: what
    `create_proxy` returns. ``destroy()`` releases the JavaScript proxy (and
    with it the reference to the Python object)."""

    __slots__ = ()

    def unwrap(self):
        """the Python object"""
        return _module._unwrap_double_proxy(self)


class _Sliceable(_Mixin):
    """``proxy[a:b:c]`` for arrays and typed arrays. The core calls
    `_getslice` when the key of ``proxy[key]`` is a slice. Also the read-only
    methods of sequences."""

    __slots__ = ()

    # These only need len() and indexing, which the proxy has: taken as they
    # are from Python's own implementation for sequences.
    index = Sequence.index
    count = Sequence.count
    __reversed__ = Sequence.__reversed__

    # (a sequence, not a mapping: see _Hidden)
    keys = _Hidden("keys")

    def _getslice(self, key):
        indices = _slice_indices(self, key)
        if indices.step == 1:
            # (JavaScript's slice(): a new array with the items start .. stop)
            return _method(self, "slice", indices.start, max(indices.stop, indices.start))
        # every n-th item / backwards: a new array of the same kind, filled
        # item by item
        result = self.constructor.new(len(indices))
        for i, index in enumerate(indices):
            result[i] = self[index]
        return result


class JSArray(_Sliceable):
    """A JavaScript ``Array``. It behaves like a Python list: indexing with
    negative indices and slices, ``len``, ``in``, iteration, and the list
    methods below. The JavaScript methods (``push``, ``map``, ...) are
    available too, except where a list method has the same name (``pop``,
    ``reverse``, ``index``): there the Python meaning wins.
    """

    __slots__ = ()

    def append(self, item):
        """Add `item` at the end."""
        self.push(_keep(item))

    def extend(self, items):
        """Add every item of the iterable `items` at the end."""
        for item in items:
            self.push(_keep(item))

    def insert(self, index, item):
        """Insert `item` before position `index`."""
        self.splice(index, 0, _keep(item))

    def pop(self, index=-1):
        """Remove the item at `index` (default: the last) and return it."""
        n = len(self)
        if n == 0:
            raise IndexError("pop from empty array")
        if not -n <= index < n:
            raise IndexError("pop index out of range")
        # (splice(i, 1) removes one item at i and returns the removed items)
        return self.splice(index, 1)[0]

    def reverse(self):
        """Reverse the order of the items, in place."""
        _method(self, "reverse")

    def clear(self):
        """Remove all items."""
        self.length = 0

    def __iadd__(self, items):
        self.extend(items)
        return self

    # (taken from Python's own implementation, like index / count above)
    remove = MutableSequence.remove

    def _setslice(self, key, items):
        # `proxy[a:b:c] = items` (called by the core)
        try:
            items = [_keep(item) for item in items]
        except TypeError:
            if not hasattr(items, "__iter__"):
                # (the message of a Python list)
                raise TypeError("must assign iterable to extended slice") from None
            raise
        indices = _slice_indices(self, key)
        if indices.step == 1:
            # like a list: the slice is replaced, the array may grow / shrink
            self.splice(indices.start, max(indices.stop - indices.start, 0), *items)
            return
        if len(items) != len(indices):
            raise ValueError(
                f"attempt to assign sequence of size {len(items)} to extended slice of size {len(indices)}"
            )
        for index, item in zip(indices, items):
            self[index] = item

    def _delslice(self, key):
        # `del proxy[a:b:c]` (called by the core)
        indices = _slice_indices(self, key)
        if indices.step == 1:
            self.splice(indices.start, max(indices.stop - indices.start, 0))
            return
        # from the back, so that removing one item does not move the ones
        # that are still to be removed
        for index in sorted(indices, reverse=True):
            self.splice(index, 1)


# the item type of each kind of typed array, as `struct` format character
_ITEM_FORMATS = {
    "Int8Array": "b",
    "Uint8Array": "B",
    "Uint8ClampedArray": "B",
    "Int16Array": "h",
    "Uint16Array": "H",
    "Int32Array": "i",
    "Uint32Array": "I",
    "BigInt64Array": "q",
    "BigUint64Array": "Q",
    "Float32Array": "f",
    "Float64Array": "d",
}
# formats that mean the same items (e.g. "l" is a 32 bit int here, like "i")
_SAME_FORMAT = {"l": "i", "L": "I", "c": "B", "?": "B"}


def _check_same_items(js_buffer, python_buffer):
    """`assign` / `assign_to` copy raw bytes. Between a typed array and a
    Python buffer of another item type (int32 into float64, ...) that would
    silently produce garbage: a ValueError instead. Raw byte buffers on
    either side (bytes, ArrayBuffer, DataView) go with everything."""
    js_format = _ITEM_FORMATS.get(js_buffer.constructor.name)
    python_format = python_buffer.format.lstrip("@=<")
    python_format = _SAME_FORMAT.get(python_format, python_format)
    if js_format is None or python_format == "B" or js_format == "B":
        return
    if js_format != python_format:
        raise ValueError(
            f"incompatible formats: the JavaScript buffer has items of type '{js_format}', "
            f"the Python buffer of type '{python_format}'"
        )


class JSBuffer(_Mixin):
    """A JavaScript typed array, ``DataView`` or ``ArrayBuffer``: a block of
    bytes."""

    __slots__ = ()

    def to_bytes(self):
        """A copy of the bytes, as ``bytes``."""
        return pyjs_core.js_to_bytes(self)[0]

    def to_memoryview(self):
        """A copy of the data as ``memoryview`` with the item type of the
        typed array (a ``Float64Array`` gives items of type ``"d"``)."""
        data, item_format = pyjs_core.js_to_bytes(self)
        return memoryview(data).cast(item_format)

    def to_string(self, encoding="utf-8"):
        """The bytes decoded as text. Bytes that are no valid text in that
        encoding are a ValueError."""
        try:
            # (fatal: throw instead of replacing invalid bytes with U+FFFD)
            return _js.TextDecoder.new(encoding, fatal=True).decode(self)
        except JSException as e:
            if e.name == "TypeError":
                raise ValueError(f"the buffer is not valid '{encoding}' text") from None
            raise

    def assign(self, source):
        """Copy the bytes of the Python buffer `source` (bytes, memoryview,
        numpy array, ...) into this JavaScript buffer. Both must have the
        same size in bytes and, for a typed array, the same item type."""
        source = memoryview(source)
        _check_same_items(self, source)
        source = source.cast("B")
        target = _bytes_of(self)
        if len(source) != target.length:
            raise ValueError(f"cannot assign {len(source)} bytes to a buffer of {target.length} bytes")
        # (a Uint8Array looking directly at the memory of `source`, no copy;
        # only valid during this statement)
        target.set(pyjs_core.buffer_to_js(source, True))

    def assign_to(self, target):
        """Copy the bytes of this JavaScript buffer into the writable Python
        buffer `target` (bytearray, numpy array, ...). Both must have the
        same size in bytes and, for a typed array, the same item type."""
        target = memoryview(target)
        _check_same_items(self, target)
        target = target.cast("B")
        data = self.to_bytes()
        if len(data) != len(target):
            raise ValueError(f"cannot assign {len(data)} bytes to a buffer of {len(target)} bytes")
        target[:] = data


# the bytes of a typed array / DataView / ArrayBuffer as Uint8Array (a view of
# the same memory, not a copy)
_bytes_of = _js.Function(
    "obj",
    "return ArrayBuffer.isView(obj) ? new Uint8Array(obj.buffer, obj.byteOffset, obj.byteLength)"
    " : new Uint8Array(obj);",
)


class JSTypedArray(JSBuffer, _Sliceable):
    """A JavaScript typed array (``Uint8Array``, ``Float64Array``, ...): a
    `JSBuffer` whose items can be read and written by index and by slice.
    Its length is fixed."""

    __slots__ = ()

    def _setslice(self, key, items):
        # `proxy[a:b:c] = items` (called by the core): the size cannot change
        items = list(items)
        indices = _slice_indices(self, key)
        if len(items) != len(indices):
            raise ValueError(f"cannot assign {len(items)} items to a slice of {len(indices)} items of a typed array")
        for index, item in zip(indices, items):
            self[index] = item


class JSMap(_Mixin):
    """A JavaScript object that works like a ``Map`` (it has ``get``,
    ``has``, ``size`` and can be iterated). It behaves like a read-only
    Python mapping: ``proxy[key]``, ``key in proxy``, ``len``, iteration
    over the *keys*, and the methods below."""

    __slots__ = ()

    def __iter__(self):
        # (the JavaScript method keys(): an iterator over the keys)
        return _method(self, "keys")

    def keys(self):
        """A view of the keys."""
        return KeysView(self)

    def values(self):
        """A view of the values."""
        return ValuesView(self)

    def items(self):
        """A view of the (key, value) pairs."""
        return ItemsView(self)

    def get(self, key, default=None):
        """The value for `key`, or `default` if there is no such key."""
        try:
            return self[key]
        except KeyError:
            return default


class JSMutableMap(JSMap):
    """A `JSMap` that can be changed (it also has ``set`` and ``delete``):
    ``proxy[key] = value``, ``del proxy[key]`` and the dict methods below."""

    __slots__ = ()

    def clear(self):
        """Remove all entries."""
        _method(self, "clear")

    def pop(self, key, *default):
        """Remove `key` and return its value; without such a key: `default`
        if given, else KeyError."""
        try:
            value = self[key]
        except KeyError:
            if default:
                return default[0]
            raise
        del self[key]
        return value

    # These only need the operations the proxy has: taken as they are from
    # Python's own implementation for mappings.
    popitem = MutableMapping.popitem
    setdefault = MutableMapping.setdefault
    update = MutableMapping.update


def _step(step):
    """The value of one step of a JavaScript (async) generator. `step` is
    what its next() / throw() / return() answered: ``{done, value}``. A
    finished generator raises StopIteration with its return value, like a
    Python generator."""
    # (the messages are pyodide's)
    if not isinstance(step, JSProxy):
        raise TypeError(f'Result should have type "object" not "{_typeof(step)}"')
    if callable(getattr(step, "then", None)):
        raise TypeError("Result was a promise, use anext() / asend() / athrow() instead.")
    if not hasattr(step, "done"):
        raise TypeError('Result has no "done" field.')
    # (`value` may be left out, e.g. `{done: true}`: then it is None)
    value = getattr(step, "value", None)
    if step.done:
        raise StopIteration(value)
    return value


# typeof of a value as JavaScript says it
_typeof = _js.Function("x", "return typeof x;")


async def _await_step(promise):
    step = await promise
    value = getattr(step, "value", None)
    if getattr(step, "done", False):
        raise StopAsyncIteration(value)
    return value


def _async_step(promise):
    """Like `_step`, for the promise of a step of an async generator. A
    future (an asyncio task), as pyodide returns: it can also be inspected
    without awaiting it (``done()``, ``exception()``)."""
    return asyncio.ensure_future(_await_step(promise))


def _exception(exc, value):
    """the exception instance for the arguments of throw(exc, value): like
    for Python generators, `exc` is an instance or an exception class"""
    if isinstance(exc, type):
        if isinstance(value, exc):
            return value
        return exc() if value is None else exc(value)
    return exc


def _stand_in(exception):
    """The JavaScript error thrown into a JavaScript generator for the
    Python `exception` (throw / athrow): JavaScript code can only catch
    JavaScript values. It is a ``PythonError``, the same kind of error
    JavaScript gets when Python code it called raises. Whenever such an
    error comes back to Python uncaught (now, or from a later ``next()``),
    the original `exception` is raised again, not a JSException."""
    return _module._python_error(exception)


class JSGenerator(_Mixin):
    """A JavaScript generator (an iterator that also has ``return`` and
    ``throw``), with the methods of a Python generator."""

    __slots__ = ()

    def send(self, value):
        """Resume the generator: its current ``yield`` evaluates to `value`.
        Returns the next yielded value; raises StopIteration at the end.
        (`value` gets a lasting proxy: the generator may keep it.)"""
        return _step(_method(self, "next", _keep(value)))

    def throw(self, exc, value=None, traceback=None):
        """Raise an exception inside the generator, at its current
        ``yield``. Returns the next yielded value."""
        return _step(_method(self, "throw", _stand_in(_exception(exc, value))))

    def close(self):
        """Finish the generator early (JavaScript's ``return()``)."""
        step = _method(self, "return")
        # (a generator can refuse to finish by yielding again in a
        # `finally` block; python reports that for its own generators too)
        if not getattr(step, "done", True):
            raise RuntimeError("JavaScript generator ignored return")


class JSAsyncIterable(_Mixin):
    """A JavaScript object with ``[Symbol.asyncIterator]``:
    ``async for x in proxy``."""

    __slots__ = ()

    def __aiter__(self):
        return _async_iterator(self)


class JSAsyncIterator(_Mixin):
    """A JavaScript iterator whose ``next()`` returns promises:
    ``await anext(proxy)``."""

    __slots__ = ()

    def __aiter__(self):
        return self

    def __anext__(self):
        return _async_step(_method(self, "next"))


class JSAsyncGenerator(JSAsyncIterator):
    """A JavaScript async generator, with the methods of a Python async
    generator."""

    __slots__ = ()

    def asend(self, value):
        """Like `JSGenerator.send`; to be awaited."""
        return _async_step(_method(self, "next", _keep(value)))

    def athrow(self, exc, value=None, traceback=None):
        """Like `JSGenerator.throw`; to be awaited."""
        return _async_step(_method(self, "throw", _stand_in(_exception(exc, value))))

    async def aclose(self):
        """Like `JSGenerator.close`; to be awaited."""
        step = await _method(self, "return")
        if not getattr(step, "done", True):
            raise RuntimeError("JavaScript async generator ignored return")


# So that isinstance(proxy, collections.abc.Sequence) etc. hold, as for the
# Python containers.
MutableSequence.register(JSArray)
Sequence.register(JSTypedArray)
Mapping.register(JSMap)
MutableMapping.register(JSMutableMap)


def mixins(flags):
    """The classes of this module that the proxy type for JavaScript objects
    with these `flags` inherits from (the core calls this once per set of
    flags). Order matters where two classes define the same method: the
    earlier one wins."""
    classes = []
    if flags & _DOUBLE_PROXY:
        classes.append(JSDoubleProxy)
    if flags & _ARRAY:
        classes.append(JSArray)
    if flags & _BUFFER:
        # (a typed array can be indexed, a DataView / ArrayBuffer cannot)
        classes.append(JSTypedArray if flags & _GETITEM else JSBuffer)
    if flags & _MAP:
        classes.append(JSMutableMap if flags & _SETITEM else JSMap)
    if flags & _GENERATOR:
        if flags & _ITERATOR:
            classes.append(JSGenerator)
        if flags & _ASYNC_ITERATOR:
            classes.append(JSAsyncGenerator)
    elif flags & _ASYNC_ITERATOR:
        classes.append(JSAsyncIterator)
    if flags & _ASYNC_ITERABLE and not flags & _ASYNC_ITERATOR:
        classes.append(JSAsyncIterable)
    if flags & _CALLABLE:
        classes.append(JSCallable)
    if flags & _AWAITABLE:
        classes.append(JSPromise)
    if flags & _ITERABLE:
        classes.append(JSIterable)
    if flags & _ITERATOR:
        classes.append(JSIterator)
    return tuple(classes)
