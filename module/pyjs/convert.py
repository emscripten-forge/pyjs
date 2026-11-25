"""Deep conversion between Python and JavaScript values.

Crossing the language border, only simple values are converted automatically
(``None``, ``bool``, numbers, ``str``). Containers are *not*: a JavaScript
array arrives in Python as a `JSProxy` (it stays a JavaScript array, Python
operates on it remotely), a Python ``list`` arrives in JavaScript as a
PyProxy. That is cheap and keeps changes visible on both sides, but sometimes
a real copy is wanted:

* `to_py` copies a JavaScript value into Python objects:
  Array -> list, Map -> dict, Set -> set, plain Object -> dict,
  typed arrays / ArrayBuffer -> memoryview
* `to_js` copies a Python value into JavaScript objects:
  list / tuple -> Array, dict -> Object, set -> Set, buffers -> typed array

Both follow PEP 818.

Round trips: the two are not exact inverses, because the languages do not
have the same containers. What survives a round trip:

    Python -> to_js -> to_py              JavaScript -> to_py -> to_js
    list   -> Array  -> list    (same)    Array  -> list   -> Array   (same)
    tuple  -> Array  -> list              Object -> dict   -> Object  (same)
    dict   -> Object -> dict    (same)    Map    -> dict   -> Object
    set    -> Set    -> set     (same)    Set    -> set    -> Set     (same)
    bytes  -> Uint8Array -> memoryview    typed array -> memoryview -> typed array

(dict keys that are no str come back as str: a JavaScript object only has
string property names, see `_js_property_name`.)
"""

import struct

import pyjs_core
from pyjs_core import JSProxy, global_this

__all__ = ["to_py", "to_js", "buffer_to_js_typed_array", "ConversionError"]

_js = global_this()


class ConversionError(Exception):
    """A value cannot be converted: `to_js` with ``create_pyproxies=False``,
    a dict key that has no JavaScript equivalent, ..."""


def _check_key(key, target):
    """Yes: a list / tuple / dict / set cannot be a key (of a dict that
    becomes a JavaScript object or Map) or an item of a set (that becomes a
    Set). A ConversionError instead.

    Why: Python compares such keys by value, JavaScript by identity. In
    Python ``d[(1, 2)]`` finds the entry for any equal tuple. Converted, the
    key would become a NEW JavaScript Array; JavaScript only finds a Map
    entry with that very Array object, which nobody else has, so the entry
    could never be looked up again (and two equal tuples would be two
    different keys). For a plain JavaScript object it is worse: the Array
    would be turned into the string "1,2". Rather than a silently broken
    result, the conversion refuses. (Use a str / number key, or keep the
    Python dict: without to_js, JavaScript gets a proxy of it.)"""
    if isinstance(key, (list, tuple, dict, set, frozenset)):
        raise ConversionError(f"Cannot use {key!r} as a key for a Javascript {target}")


# JavaScript's String(): the property name JavaScript makes of a number
_js_string = _js.String


def _js_property_name(key):
    """The name of the JavaScript property a dict key becomes, or None for
    keys that are no simple value.

    A key that is not a str is written to JavaScript as the value it is (a
    number, true / false, undefined), and JavaScript turns it into a string
    when it becomes the property name (a JavaScript object has only string
    property names): ``{True: 1}`` becomes ``{"true": 1}``, ``{1: 2}``
    becomes ``{"1": 2}``, ``obj[1.0]`` is the property "1". The conversion
    does not do that itself, JavaScript does; this function only predicts it.
    This has to give exactly that string, or two keys that end up as the
    same property are not noticed. ints and str read the same in both
    languages. floats do not: JavaScript writes 1.0 as "1", inf as
    "Infinity", 1e21 as "1e+21", 1e-7 as "1e-7" (Python: "1.0", "inf",
    "1e+21", "1e-07"), so JavaScript itself is asked (only for float keys)."""
    if isinstance(key, bool):
        return "true" if key else "false"
    if key is None:
        return "undefined"
    if isinstance(key, float):
        return str(_js_string(key))
    if isinstance(key, (int, str)):
        return str(key)
    return None


def _check_dict_keys(d):
    """The keys of a dict that becomes a plain JavaScript object: no
    containers, and no two keys that are the same property in JavaScript
    (``{1: ..., "1": ...}``: both are the property "1", one value would be
    lost silently). Called by the core for dicts with keys other than str."""
    seen = set()
    for key in d:
        _check_key(key, "object")
        name = _js_property_name(key)
        if name is None:
            continue
        if name in seen:
            raise ConversionError(f"Key collision when converting Python dictionary to JavaScript. Key: {name!r}")
        seen.add(name)


# ---------------------------------------------------------------------------
# JavaScript -> Python
# ---------------------------------------------------------------------------
# What kind of container a JavaScript object is, as number (one call instead
# of several `instanceof` questions from Python):
#   1 Array, 2 Map, 3 Set, 4 typed array / ArrayBuffer / DataView,
#   5 plain object ({...}: its constructor is Object or it has none),
#   0 anything else (stays a proxy: a DOM node, a class instance, a function)
_kind = _js.Function(
    "obj",
    """
    if (Array.isArray(obj)) { return 1; }
    const tag = Object.prototype.toString.call(obj);
    if (tag === "[object NodeList]" || tag === "[object HTMLCollection]") { return 1; }
    if (obj instanceof Map) { return 2; }
    if (obj instanceof Set) { return 3; }
    if (ArrayBuffer.isView(obj) || obj instanceof ArrayBuffer) { return 4; }
    if (typeof obj !== "object") { return 0; }
    const constructor = obj.constructor;
    return (constructor === undefined || constructor === Object) ? 5 : 0;
    """,
)
_ARRAY, _MAP, _SET, _BUFFER, _OBJECT = 1, 2, 3, 4, 5

# the entries of a Map / a plain object as one flat array [key0, value0, key1,
# value1, ...]: iterating one array is far fewer calls into JavaScript than
# asking for every pair
_flat_map = _js.Function("map", "const out = []; for (const [k, v] of map) { out.push(k, v); } return out;")
_flat_object = _js.Function(
    "obj", "const out = []; for (const k of Object.keys(obj)) { out.push(k, obj[k]); } return out;"
)


def _buffer_to_memoryview(js_buffer):
    """What `to_py` makes of a typed array / ArrayBuffer: a memoryview with
    the item type of the typed array (Float64Array -> format 'd').

    Why "of a copy": the bytes of a JavaScript buffer live outside the wasm
    memory, where Python cannot look at them. So they are copied once into a
    new Python ``bytes`` object (`js_to_bytes`), and the memoryview is a
    typed view of THAT (``cast``, no second copy). The result is
    independent of the JavaScript buffer: changing one does not change the
    other (like every result of to_py). Same as `JSBuffer.to_memoryview`."""
    data, fmt = pyjs_core.js_to_bytes(js_buffer)
    view = memoryview(data)
    return view if fmt == "B" else view.cast(fmt)


def _to_py(obj, depth, cache, default_converter):
    """`to_py` for one value; `cache`: js_id -> the Python object already made
    for that JavaScript object (objects referenced twice or in a cycle are
    converted once)"""
    if depth == 0 or not isinstance(obj, JSProxy):
        return obj
    kind = _kind(obj)
    if kind == _BUFFER:
        return _buffer_to_memoryview(obj)

    key = obj.js_id
    if key in cache:
        return cache[key]

    def convert(value):
        """convert a value one level further down"""
        return _to_py(value, depth - 1, cache, default_converter)

    if kind == _ARRAY:
        result = cache[key] = []
        for item in obj:
            result.append(convert(item))
    elif kind == _SET:
        result = cache[key] = set()
        for item in obj:
            result.add(convert(item))
    elif kind == _MAP or kind == _OBJECT:
        result = cache[key] = {}
        flat = iter(_flat_map(obj) if kind == _MAP else _flat_object(obj))
        for k in flat:
            result[convert(k)] = convert(next(flat))
    elif default_converter is not None:
        # something else: let the caller decide

        def cache_conversion(js_obj, py_obj):
            """remember `py_obj` as the conversion of `js_obj`"""
            cache[js_obj.js_id] = py_obj

        result = default_converter(obj, convert, cache_conversion)
    else:
        result = obj
    return result


def to_py(obj, *, depth=-1, default_converter=None):
    """Convert a JavaScript value into Python objects (a deep copy).

    Args:
        obj: a `JSProxy`. Any other value is returned as is, so this can be
            called on whatever JavaScript returned.
        depth: how many levels of containers to convert, -1 for all. With
            ``depth=1`` an array of arrays becomes a list of proxies.
        default_converter: called as ``default_converter(js_obj, convert,
            cache_conversion)`` for objects that are none of the containers
            above; returns their conversion. ``convert(value)`` converts a
            nested value, ``cache_conversion(js_obj, py_obj)`` registers the
            result early (needed for self referencing objects).

    Example:
    ```python
    js_array = js.Function("return [1, 2, {a: 3}]")()
    assert to_py(js_array) == [1, 2, {"a": 3}]
    ```
    """
    if default_converter is None:
        # The normal case is done by the core in one call into JavaScript for
        # the whole structure (src/deep.cpp). The Python code in this file
        # does the same thing step by step; it is only needed when a
        # converter function has to be asked about individual objects.
        return pyjs_core.to_py(obj, depth)
    return _to_py(obj, depth, {}, default_converter)


def _to_py_with_converter(obj, depth, default_converter):
    """`to_py` with a converter function, step by step. Called by the core
    for the method form, ``js_obj.to_py(default_converter=...)`` (without a
    converter that method does everything in the core itself)."""
    return _to_py(obj, depth, {}, default_converter)


# ---------------------------------------------------------------------------
# Python -> JavaScript
# ---------------------------------------------------------------------------
_new_array = _js.Function("return [];")
_is_js_array = _js.Array.isArray
_new_object = _js.Function("return {};")
_new_set = _js.Function("return new Set();")
# Sets a property whose name is only known at runtime. In python the
# properties of a JavaScript object are attributes (`obj.name = v`), and
# `obj[key] = v` is reserved for containers like arrays and Maps, so this
# takes a small JavaScript function. (setattr(obj, key, v) would also work
# for strings, but dict keys can be numbers too.)
_set_property = _js.Function("obj", "key", "value", "obj[key] = value;")

# what needs no conversion: it is converted (or unwrapped) automatically when
# it is passed to JavaScript
_PASSED_AS_IS = (type(None), bool, int, float, str, JSProxy)


def _is_buffer(obj):
    """bytes, bytearray, memoryview, numpy arrays, ...: anything with the
    buffer protocol"""
    try:
        memoryview(obj)
    except TypeError:
        return False
    return True


# Self-referencing structures with a `dict_converter`.
#
# `to_js` remembers every container it converted (the `cache`: id(python
# object) -> its JavaScript object), so that an object referenced twice
# becomes ONE JavaScript object, and a structure that contains itself
# (``d = {}; d["self"] = d``) does not recurse forever.
#
# Normally the JavaScript object is created first and filled afterwards, so
# it is in the cache before its contents are converted. With a
# `dict_converter` (e.g. ``js.Map.new``) that is impossible: the converter
# builds the object from the list of all converted entries, i.e. only AFTER
# them. A reference to the dict from inside its own entries finds the dict
# still "under construction": the cache holds this marker, `_store` notes
# where the object will have to go, and `_fill_in` puts it there once it
# exists.
_PENDING = object()


def _to_js(obj, depth, cache, options):
    """`to_js` for one value; `cache`: id(python object) -> the JavaScript
    object already made for it"""
    if isinstance(obj, _PASSED_AS_IS):
        return obj
    key = id(obj)
    if key in cache:
        return cache[key]
    if depth == 0:
        # The depth limit is reached: `obj` is not converted. It still must
        # not be returned as it is: it ends up stored inside a JavaScript
        # container, and a Python object handed to JavaScript the normal way
        # only lives for one call. So it gets a lasting proxy.
        return _lasting_proxy(obj, key, cache, options)

    eager_converter = options["eager_converter"]
    if eager_converter is not None:
        # The caller's converter goes first: it may handle anything. Its
        # `convert(value)` is the normal conversion of `value` (for `obj`
        # itself: of its contents, which go through the eager converter
        # again).

        def convert(value):
            return _convert_normally(value, depth, cache, options)

        return _kept(eager_converter(obj, convert, _cache_conversion(cache)), options)
    return _convert_normally(obj, depth, cache, options)


def _cache_conversion(cache):
    """the `cache_conversion(py_obj, js_obj)` function the converters get:
    register a result early (needed for self referencing structures)"""

    def cache_conversion(py_obj, js_obj):
        cache[id(py_obj)] = js_obj

    return cache_conversion


def _kept(result, options):
    """What a converter function returned, ready to be stored in a
    JavaScript container: a Python object (not converted by the converter)
    needs a lasting proxy, see `_lasting_proxy`."""
    if isinstance(result, _PASSED_AS_IS):
        return result
    return _lasting_proxy(result, id(result), {}, options)


def _store(container, slot, value, obj_key_of, options):
    """``container[slot] = value`` in JavaScript, for the result of
    converting one item / entry.

    The value may be the marker `_PENDING` (its JavaScript object does not
    exist yet, see there). Then the slot is set to undefined for now and
    noted in ``options["fill_in"]`` under the cache key `obj_key_of`;
    `_fill_in` writes the real object there later."""
    if value is _PENDING:
        options["fill_in"].setdefault(obj_key_of, []).append((container, slot))
        value = None
    _set_property(container, slot, value)


def _convert_normally(obj, depth, cache, options):
    """The built-in conversion of `obj` (list -> Array, dict -> Object, ...).

    "Eager" refers to the option ``eager_converter`` of `to_js` (pyodide's
    name): a function of the caller that is asked FIRST, for every value,
    before the built-in rules (unlike ``default_converter``, which is only
    asked for what the built-in rules cannot convert). It gets a `convert`
    callback for the values it does not want to handle itself; that callback
    is this function: the built-in conversion of the value, whose contents
    then go through the eager converter again (see `_to_js`)."""
    if isinstance(obj, _PASSED_AS_IS):
        return obj
    key = id(obj)
    if key in cache:
        return cache[key]

    def convert(value):
        """convert a value one level further down"""
        return _to_js(value, depth - 1, cache, options)

    def pending_key(value):
        """the cache key of `value` if its conversion is still pending"""
        return id(value)

    if isinstance(obj, dict):
        dict_converter = options["dict_converter"]
        if dict_converter is not None:
            # the caller builds the object from [key, value] pairs (e.g.
            # js.Map.new, js.Object.fromEntries)
            cache[key] = _PENDING
            entries = _new_array()
            for k, v in obj.items():
                _check_key(k, "Map")
                pair = _new_array()
                pair.push(convert(k))
                _store(pair, 1, convert(v), pending_key(v), options)
                entries.push(pair)
            result = cache[key] = dict_converter(entries)
            _fill_in(key, result, options)
        else:
            _check_dict_keys(obj)
            result = cache[key] = _new_object()
            for k, v in obj.items():
                # (a property with a computed name: `result[k] = v` in JS)
                _store(result, convert(k), convert(v), pending_key(v), options)
    elif isinstance(obj, (set, frozenset)):
        result = cache[key] = _new_set()
        for item in obj:
            _check_key(item, "Set")
            result.add(convert(item))
    elif _is_buffer(obj):
        # bytes, numpy arrays, ...: a typed array with a copy of the items
        try:
            result = cache[key] = pyjs_core.buffer_to_js(obj, False)
        except (TypeError, BufferError):
            # no flat block of numbers (several dimensions, PIL style
            # suboffsets): nested Arrays of typed arrays
            result = cache[key] = _convert_normally(_buffer_rows(obj), depth, cache, options)
    # (only lists and tuples, as in pyodide: other sequences, like range,
    # stay Python objects and become proxies, below)
    elif isinstance(obj, (list, tuple)):
        result = cache[key] = _new_array()
        for index, item in enumerate(obj):
            _store(result, index, convert(item), pending_key(item), options)
    else:
        default_converter = options["default_converter"]
        if default_converter is not None:
            return _kept(default_converter(obj, convert, _cache_conversion(cache)), options)
        result = _lasting_proxy(obj, key, cache, options)
    return result


def _buffer_rows(obj):
    """A buffer that is no flat block of items (several dimensions, or
    scattered in memory like PIL images with "suboffsets") as nested lists
    whose innermost level are flat buffers of one row each. to_js makes
    nested Arrays of typed arrays from that (as pyodide)."""
    view = memoryview(obj)
    item = view.format.lstrip("@=<")

    def build(items, level):
        if level == view.ndim - 1:
            # one row: a flat copy with the item type
            return memoryview(bytearray(struct.pack(f"{len(items)}{item}", *items))).cast(item)
        return [build(row, level + 1) for row in items]

    return build(view.tolist(), 0)


def _fill_in(key, result, options):
    """The JavaScript object `result` of a dict (cache key `key`) exists
    now: write it into every slot that referenced the dict while it was
    still under construction (noted by `_store`, see `_PENDING`)."""
    for container, slot in options["fill_in"].pop(key, []):
        _set_property(container, slot, result)


def _lasting_proxy(obj, key, cache, options):
    """A Python object that `to_js` cannot convert (an instance of a
    custom class, a function, a range, ...) stays a Python object:
    JavaScript gets a proxy of it. It has to be a lasting one (create_proxy):
    the converted structure holds on to it after `to_js` returned. Whoever
    called `to_js` destroys it later (option `pyproxies` collects them).

    With ``create_pyproxies=False`` the caller said "no proxies, only real
    copies": then such an object is an error (ConversionError), rather than
    a proxy the caller does not expect and would never destroy."""
    if not options["create_pyproxies"]:
        raise ConversionError(f"cannot convert an object of type {type(obj).__name__} to JavaScript")
    # (read back from the result in python, it is the object again; the
    # proxies collected in `pyproxies` are destroyed in JavaScript by
    # destroy_proxies, as in pyodide)
    proxy = cache[key] = pyjs_core.create_proxy(obj)
    pyproxies = options["pyproxies"]
    if pyproxies is not None:
        pyproxies.append(proxy)
    return proxy


def to_js(
    obj,
    *,
    depth=-1,
    pyproxies=None,
    create_pyproxies=True,
    dict_converter=None,
    default_converter=None,
    eager_converter=None,
):
    """Convert a Python value into JavaScript objects (a deep copy).

    list / tuple -> Array, dict -> Object, set -> Set, buffers (bytes, numpy
    arrays, ...) -> typed array. ``None``, ``bool``, numbers, ``str`` and
    `JSProxy` objects are returned as they are: they are converted
    automatically when passed to JavaScript. Other objects become proxies,
    including other sequences (``range``, ``deque``, ...), as in pyodide:
    ``to_js(list(r))`` copies one.

    Args:
        obj: the value to convert.
        depth: how many levels of containers to convert, -1 for all.
        pyproxies: a JavaScript Array (``js.Array.new()``). The proxies
            created for objects that cannot be converted are appended, so
            that the caller can destroy them later (`destroy_proxies`).
        create_pyproxies: if False, raise `ConversionError` instead of
            creating a proxy.
        dict_converter: what a dict becomes: called with a JavaScript array of
            ``[key, value]`` pairs, e.g. ``js.Map.new`` for a Map. Default: a
            plain Object.
        default_converter: called as ``default_converter(obj, convert,
            cache_conversion)`` for objects that are none of the containers
            above, instead of creating a proxy.
        eager_converter: like `default_converter`, but called for every
            container first.

    Example:
    ```python
    js_obj = to_js({"a": [1, 2]})
    assert js.JSON.stringify(js_obj) == '{"a":[1,2]}'
    js_map = to_js({"a": 1}, dict_converter=js.Map.new)
    assert js_map.get("a") == 1
    ```
    """
    if pyproxies is not None and not _is_js_array(pyproxies):
        raise TypeError("to_js: pyproxies must be a JavaScript Array (e.g. js.Array.new())")
    if isinstance(obj, _PASSED_AS_IS):
        return obj
    if (
        pyproxies is None
        and create_pyproxies
        and dict_converter is None
        and default_converter is None
        and eager_converter is None
    ):
        # The normal case is done by the core in one call into JavaScript for
        # the whole structure (src/deep.cpp). The Python code below does the
        # same thing step by step; it is only needed when one of the options
        # wants a say about individual objects.
        return pyjs_core.to_js(obj, depth)
    options = dict(
        pyproxies=pyproxies,
        create_pyproxies=create_pyproxies,
        dict_converter=dict_converter,
        default_converter=default_converter,
        eager_converter=eager_converter,
        # see _PENDING
        fill_in={},
    )
    return _to_js(obj, depth, {}, options)


def buffer_to_js_typed_array(buffer, view=False):
    """A JavaScript typed array for a contiguous 1d buffer of numbers (bytes,
    ``array.array``, a numpy array, ...); the item type decides which one
    (float64 -> Float64Array).

    Args:
        buffer: the buffer.
        view: False: the typed array holds a copy of the items. True: it is a
            view of the memory of `buffer`, without copying. Fast, but only
            valid while `buffer` is alive and unchanged in size, and until
            the WebAssembly memory grows (any allocation can do that): use it
            right away and do not keep it.
    """
    return pyjs_core.buffer_to_js(buffer, bool(view))
