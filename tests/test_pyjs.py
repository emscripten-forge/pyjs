"""The foreign function interface from the python side: proxies of JS
objects, conversions, errors."""

import operator
import sys
from types import NoneType

import js
import pytest

from helpers import *

import pyjs

def _optional_missing(module):
    """an optional stdlib extension module (its own package with a split
    python) that is not installed: tested by test_stdlib.py instead"""
    import importlib.util

    return importlib.util.find_spec(module) is None


@pytest.mark.skipif(_optional_missing("_ssl"), reason="python-ssl not installed (test_stdlib.py)")
def test_ssl_import():
    import ssl


@pytest.mark.skipif(_optional_missing("_lzma"), reason="python-lzma not installed (test_stdlib.py)")
def test_import_lzma():
    import lzma

def test_js_module():
    # JavaScript's global scope under its three names
    import js
    from js import Function
    import jstypes.global_this
    from jstypes.global_this import Object

    assert Function('return "hello_world"')() == "hello_world"
    assert js.Function == Function
    assert jstypes.global_this.Object == Object
    assert pyjs.js.Object == Object
    with pytest.raises(ImportError):
        from js import no_such_global_xyz  # noqa: F401


def test_jstypes_names():
    # the names of PEP 818
    from jstypes.code import run_js
    from jstypes.ffi import (
        JSBigInt,
        JSException,
        JSNull,
        JSProxy,
        create_once_callable,
        create_proxy,
        destroy_proxies,
        jsnull,
        to_js,
    )

    assert run_js("1 + 1") == 2
    assert JSProxy is pyjs.JSProxy
    assert JSException is pyjs.JSException
    assert jsnull is pyjs.jsnull and isinstance(jsnull, JSNull)
    assert issubclass(JSBigInt, int)
    assert create_proxy is pyjs.create_proxy
    assert create_once_callable is pyjs.create_once_callable
    assert destroy_proxies is pyjs.destroy_proxies
    assert to_js is pyjs.to_js


def test_js_function_creation():
    f = pyjs.js.Function(
        "arg0",
        """
        return "hello_" + arg0
    """,
    )
    ret = f("world")
    assert ret == "hello_world"


def test_pyodide_polyfill():
    # Test imports
    from pyodide.ffi import JsException, JsProxy, to_js
    assert JsException is pyjs.JSException
    assert JsProxy is pyjs.JSProxy
    assert to_js is pyjs.to_js
    if pyjs.pyjs_core._module._IS_BROWSER_MAIN_THREAD:
        from js import console, window
    if pyjs.pyjs_core._module._IS_BROWSER_WORKER_THREAD:
        from js import console, postMessage

    with pytest.raises(AttributeError):
        from pyodide import ffi
        ffi.foo


def test_pyodide_polyfill_run_js():
    """`pyodide.code.run_js` evaluates JS in the global scope (imgui_bundle
    uses it to build JS helpers)."""
    from pyodide.code import run_js
    assert run_js("1 + 2") == 3
    make_pair = run_js("(a, b) => [a, b]")
    assert pyjs.to_py(make_pair(1, "two")) == [1, "two"]
    run_js("var _pyjs_test_run_js_global = 42")
    assert pyjs.js._pyjs_test_run_js_global == 42
    run_js("delete globalThis._pyjs_test_run_js_global")


def test_create_once_callable_nullary():
    def pyfunc():
        return "hello_from_pyfunc"

    js_once_callable = pyjs.create_once_callable(pyfunc)

    # call the first time
    ret = js_once_callable()
    assert ret == "hello_from_pyfunc"

    with pytest.raises(Exception):
        # call the second time
        ret = js_once_callable()

    with pytest.raises(Exception):
        # call the third time
        ret = js_once_callable()


def test_create_proxy():
    def pyfunc():
        return "hello_from_pyfunc"

    # a lasting JS stand-in for a python object ...
    js_cb = pyjs.create_proxy(pyfunc)
    assert isinstance(js_cb, pyjs.JSProxy)
    # ... callable from python too (it goes through JS and back)
    assert js_cb() == "hello_from_pyfunc"
    # JS can keep and use it after the call it was passed to
    store = pyjs.js.Function("f", "globalThis.__pyjs_test_cb = f;")
    call = pyjs.js.Function("return globalThis.__pyjs_test_cb();")
    try:
        store(js_cb)
        assert call() == "hello_from_pyfunc"
        js_cb.destroy()
        with pytest.raises(pyjs.JSException):
            call()
    finally:
        pyjs.js.Function("delete globalThis.__pyjs_test_cb;")()


def test_create_proxy_of_converted_values():
    # values that are converted to JS values have no proxy
    for value in (None, True, 1, 1.5, "text", pyjs.jsnull):
        with pytest.raises(TypeError):
            pyjs.create_proxy(value)


parameters = [
    # special items: undefined is None, null is jsnull
    ("undefined", NoneType, None, (lambda x, should_val: x is None)),
    ("null", pyjs.JSNull, None, (lambda x, should_val: x is pyjs.jsnull)),
    # basic items
    ("42", int, 42, operator.eq),
    ("-42", int, -42, operator.eq),
    ("17.5", float, 17.5, operator.eq),
    ("false", bool, False, operator.eq),
    ("true", bool, True, operator.eq),
    # various strings
    ('"42"', str, "42", operator.eq),
    ('""', str, "", operator.eq),
    ('"undefined"', str, "undefined", operator.eq),
    ('"null"', str, "null", operator.eq),
    # set
    ("new Set([1,2,5])", set, set([1, 2, 5]), operator.eq),
    # map
    (
        "new Map([[1, 'one'],[2, 'two']])",
        dict,
        {1: "one", 2: "two"},
        operator.eq,
    ),
    # functions
    ("function(){}", pyjs.JSProxy, None, (lambda x, y: True)),
    # nested objects
    ('[1,2,"three"]', list, [1, 2, "three"], nested_eq),
    (
        "{ foo : { bar:1 }, fobar: [1,1,2] }",
        dict,
        {"foo": {"bar": 1}, "fobar": [1, 1, 2]},
        nested_eq,
    ),
]

@pytest.mark.parametrize(
    "test_input,expected_type,expected_value,comperator",
    parameters
)
def test_to_py(test_input, expected_type, expected_value, comperator):
    py_val = pyjs.to_py(ensure_js(test_input))
    assert isinstance(py_val, expected_type)
    assert comperator(py_val, expected_value)


# a typed array becomes a memoryview of a copy, with the same item type:
# JS expression -> (struct format character, the items)
@pytest.mark.parametrize(
    "test_input,expected_format,expected_items",
    [
        ("new Uint8Array([1,2,3])", "B", [1, 2, 3]),
        ("new Uint8ClampedArray([1,2,300])", "B", [1, 2, 255]),
        ("new Int8Array([-1,2,-3])", "b", [-1, 2, -3]),
        ("new Uint16Array([1,2,300])", "H", [1, 2, 300]),
        ("new Int16Array([-1,2,-300])", "h", [-1, 2, -300]),
        ("new Uint32Array([1,2,300])", "I", [1, 2, 300]),
        ("new Int32Array([-1,2,-300])", "i", [-1, 2, -300]),
        ("new BigInt64Array([-1n, 2n ** 40n])", "q", [-1, 2**40]),
        ("new BigUint64Array([1n, 2n ** 63n])", "Q", [1, 2**63]),
        ("new Float32Array([-10.5, 0.0, 1.5])", "f", [-10.5, 0.0, 1.5]),
        ("new Float64Array([-10.5, 0.0, 1.55])", "d", [-10.5, 0.0, 1.55]),
        # an ArrayBuffer has no item type: bytes
        ("new Uint8Array([1,2,3]).buffer", "B", [1, 2, 3]),
    ],
)
def test_typed_array_to_py(test_input, expected_format, expected_items):
    view = pyjs.to_py(ensure_js(test_input))
    assert isinstance(view, memoryview)
    assert view.format == expected_format
    assert view.tolist() == expected_items
    # the method form gives the same
    assert ensure_js(test_input).to_py().tolist() == expected_items


def test_typed_array_to_py_is_a_copy():
    js_array = ensure_js("new Uint8Array([1,2,3])")
    view = pyjs.to_py(js_array)
    js_array[0] = 9
    assert view.tolist() == [1, 2, 3]


def test_typed_array_view_of_part_of_a_buffer():
    # a typed array that covers only part of its ArrayBuffer (an offset)
    view = pyjs.js.Function(
        """
        const buffer = new ArrayBuffer(8);
        const all = new Uint8Array(buffer);
        for (let i = 0; i < all.length; i++) { all[i] = i; }
        return new Uint8Array(buffer, 4, 2);
        """
    )()
    assert pyjs.to_py(view).tolist() == [4, 5]


def test_numpy_arrays():
    numpy = pytest.importorskip("numpy")
    # numpy array -> typed array of the same item type (a copy)
    for dtype, js_class in [("uint8", "Uint8Array"), ("int32", "Int32Array"), ("float64", "Float64Array")]:
        array = numpy.arange(4, dtype=dtype)
        js_array = pyjs.to_js(array)
        assert js_array.constructor.name == js_class, (dtype, js_array.constructor.name)
        assert pyjs.to_py(js.Array.from_(js_array)) == [0, 1, 2, 3]
        # ... and back, through the memoryview
        back = numpy.array(js_array.to_py())
        assert back.dtype == array.dtype
        assert numpy.array_equal(back, array)
    # the same without copying: a view of the memory of the numpy array
    array = numpy.arange(4, dtype="float64")
    js_view = pyjs.buffer_to_js_typed_array(array, view=True)
    js_view[0] = 7.5
    assert array[0] == 7.5


@pytest.mark.parametrize(
    "test_input,expected_length",
    [
        ("new Uint8Array([1,2,3])", 3),
        ("new Uint16Array([1,2,3,4])", 4),
        ("new Float64Array([])", 0),
    ],
)
def test_typed_array_buffer_len(test_input, expected_length):
    assert len(pyjs.to_py(ensure_js(test_input))) == expected_length


@pytest.mark.parametrize(
    "test_input",
    [
        True,
        False,
        None,
        1,
        1.0,
        "fubar",
        set([1, 2, 3]),
        [1, 2, 3],
        # (a dict becomes a JS object, whose keys are strings)
        {"one": [1, 2], "two": {"one": [1, 2, "three"]}},
    ],
)
def test_roundtrip_py_js_py(test_input):
    if test_input is not None:
        assert to_js_to_py(test_input) == test_input
    else:
        assert to_js_to_py(test_input) is None


def test_map_to_py():
    js_map = pyjs.js.Function("return new Map([[1, 'one'],[2, 'two']])")()
    py_map = pyjs.to_py(js_map)
    len(py_map) == 2
    assert 1 in py_map
    assert 2 in py_map
    assert py_map[1] == "one"
    assert py_map[2] == "two"


def test_to_js_dict():
    # a dict becomes a plain JS object
    jsobj = pyjs.to_js({"a": 1, "b": [2, 3]})
    assert pyjs.js.JSON.stringify(jsobj) == '{"a":1,"b":[2,3]}'
    assert jsobj.a == 1


def test_to_js_dict_as_map():
    # ... or what dict_converter makes of its [key, value] pairs
    pydict = {1: "a"}
    jsmap = pyjs.to_js(pydict, dict_converter=pyjs.js.Map.new)
    # (a proxy of a Map behaves like a python mapping)
    assert list(jsmap.keys()) == [1]
    assert list(jsmap.values()) == ["a"]

    assert jsmap.get(1) == "a"


def test_to_js_depth():
    # depth=1: only the outer list is converted, the inner one stays python
    pyproxies = pyjs.js.Array.new()
    jsarray = pyjs.to_js([[1, 2], 3], depth=1, pyproxies=pyproxies)
    is_array = pyjs.js.Array.isArray
    assert is_array(jsarray)
    assert not is_array(jsarray[0])
    assert len(pyproxies) == 1
    assert pyjs.js.Function("l", "return l.get(1);")(pyproxies[0]) == 2
    pyjs.destroy_proxies(pyproxies)


def test_to_js_without_proxies():
    class Custom:
        pass

    with pytest.raises(pyjs.ConversionError):
        pyjs.to_js([Custom()], create_pyproxies=False)


def test_to_js_dict_converter():
    pydict = {"a": 1, "b": [2, {"c": "three"}]}
    jsobj = pyjs.to_js(pydict, dict_converter=pyjs.js.Object.fromEntries)
    assert pyjs.js.JSON.stringify(jsobj) == '{"a":1,"b":[2,{"c":"three"}]}'


def test_iterate_py_object_in_js():
    # python objects passed to js are proxies that implement Symbol.iterator
    blob = pyjs.js.Blob.new(["hello", "world"])
    assert blob.size == 10

    jsarray = getattr(pyjs.js.Array, "from")([1, "two", 3.5])
    assert pyjs.js.JSON.stringify(jsarray) == '[1,"two",3.5]'

    jsarray = getattr(pyjs.js.Array, "from")({"a": 1, "b": 2})
    assert pyjs.js.JSON.stringify(jsarray) == '["a","b"]'


def test_bytes_to_js():
    pyjs.to_js(b"\x00").byteLength == 1



def test_to_js_none():

    jsval = pyjs.to_js(None)
    assert pyjs.pyjs_core._module._is_undefined(jsval)


@pytest.mark.parametrize(
    "test_input,expected_output",
    [
        (lambda: "42", "42"),
        (lambda: "{}", "[object Object]"),
        (lambda: "[1, 2, 3]", "1,2,3"),
    ],
)
def test_to_str(test_input, expected_output):

    j_test_input = ensure_js(test_input())
    as_str = str(j_test_input)
    assert isinstance(as_str, str)
    assert as_str == expected_output


def test_js_null():
    # JS null is the singleton jsnull: falsy, not None
    null = eval_jsfunc("null")
    assert null is pyjs.jsnull
    assert pyjs.JSNull() is pyjs.jsnull
    assert null is not None
    assert not null
    assert repr(null) == "jsnull"
    # and goes back to JS as null
    assert pyjs.js.Function("x", "return x === null;")(pyjs.jsnull) is True


def test_js_undefined():
    # JS undefined is None
    assert eval_jsfunc("undefined") is None
    assert pyjs.js.Function("x", "return x === undefined;")(None) is True


def test_big_int():
    # a JS BigInt is an int (of type JSBigInt)
    big = eval_jsfunc("2n ** 70n")
    assert isinstance(big, pyjs.JSBigInt)
    assert big == 2**70
    # an int too large for a JS number becomes a BigInt
    assert pyjs.js.Function("x", "return typeof x;")(2**70) == "bigint"
    assert pyjs.js.Function("x", "return x === 2n ** 70n;")(2**70) is True
    assert pyjs.js.Function("x", "return typeof x;")(2**40) == "number"
    # JSBigInt: always a BigInt
    assert pyjs.js.Function("x", "return typeof x;")(pyjs.JSBigInt(5)) == "bigint"
    # large whole numbers (above 2^31) are ints, not truncated
    assert eval_jsfunc("2 ** 40") == 2**40


@pytest.mark.parametrize(
    "test_input,expected_output",
    [
        # ("[]",0),
        ("[0]", 1),
        ("[0,1,2]", 3),
        ("[[1,1,2,3],1,2]", 3),
        ("new Set([1,2])", 2),
        ("new Map([[1,2]])", 1),
        # (a JS string is a python str)
        ("'some_string'", 11),
    ],
)
def test_len(test_input, expected_output):
    assert len(ensure_js(test_input)) == expected_output


def test_len_of_object_without_length():
    # like for python objects: no length, no len()
    with pytest.raises(TypeError):
        len(eval_jsfunc("{foo:1}"))


# (container and query are JS expressions)
@pytest.mark.parametrize(
    "container,query,expected_output",
    [
        ("[1,2,3]", '"1"', False),
        ('["1",2,3]', '"1"', True),
        ("[1,2,3]", "1", True),
        ("[1,2,3]", '"4"', False),
        ("new Set([1,2,3])", "2", True),
        ("new Map([[1,2]])", "2", False),
    ],
)
def test_contains(container, query, expected_output):
    assert (ensure_js(query) in ensure_js(container)) == expected_output


def test_eq():
    # two proxies are equal iff they are the same JS object (===)
    obj = eval_jsfunc("{}")
    same = pyjs.js.Function("x", "return x;")(obj)
    other = eval_jsfunc("{}")
    assert obj is not same
    assert obj == same
    assert not (obj != same)
    assert obj != other
    assert obj != 1
    # equal proxies have the same hash and the same js_id
    assert hash(obj) == hash(same)
    assert obj.js_id == same.js_id
    assert obj.js_id != other.js_id
    assert len({obj, same, other}) == 2


def test_array_iterator():
    array = eval_jsfunc('[1,2,"three"]')
    py_array = [pyjs.to_py(v) for v in array]
    assert len(py_array) == 3
    assert py_array == [1, 2, "three"]

    # make sure that elements of iterator
    # are still js values
    array = eval_jsfunc('[{fo:"bar"}]')
    element = next(iter(array))
    assert element.typeof == "object"


def test_custom_converter():
    rectangle = pyjs.js.Function(
        """
        class Rectangle {
          constructor(height, width) {
            this.height = height;
            this.width = width;
          }
        }
        return new Rectangle(10,20)
    """
    )()

    # an instance of a class is not a plain object: it stays a proxy
    r = pyjs.to_py(rectangle)
    assert isinstance(r, pyjs.JSProxy)
    assert r.height == 10

    class Rectangle(object):
        def __init__(self, height, width):
            self.height = height
            self.width = width

    def rectangle_converter(js_val, convert, cache_conversion):
        if js_val.constructor.name == "Rectangle":
            return Rectangle(js_val.height, js_val.width)
        return js_val

    r = pyjs.to_py(rectangle, default_converter=rectangle_converter)
    assert isinstance(r, Rectangle)
    assert r.height == 10
    assert r.width == 20

    # also for objects nested in containers, and as method of the proxy
    nested = pyjs.js.Function("r", "return [r, {r: r}];")(rectangle)
    converted = nested.to_py(default_converter=rectangle_converter)
    assert isinstance(converted[0], Rectangle)
    assert isinstance(converted[1]["r"], Rectangle)


def test_custom_to_js_converter():
    class Point(object):
        def __init__(self, x, y):
            self.x = x
            self.y = y

    def point_converter(obj, convert, cache_conversion):
        if isinstance(obj, Point):
            return pyjs.to_js({"x": obj.x, "y": obj.y})
        return obj

    jsobj = pyjs.to_js([Point(1, 2)], default_converter=point_converter)
    assert pyjs.js.JSON.stringify(jsobj) == '[{"x":1,"y":2}]'


def test_python_keyword_attributes():
    # JS names that are python keywords: with a trailing underscore
    array_from = pyjs.js.Array.from_
    assert pyjs.to_py(array_from("ab")) == ["a", "b"]


def test_kwargs_are_a_trailing_object():
    f = pyjs.js.Function("a", "options", "return a + options.b + options.c;")
    assert f(1, b=2, c=3) == 6


def test_borrowed_proxies_are_destroyed_after_the_call():
    # a python object passed to JS is only usable during the call ...
    keep = pyjs.js.Function("obj", "globalThis.__pyjs_test_kept = obj;")
    use = pyjs.js.Function("return globalThis.__pyjs_test_kept.get(0);")
    try:
        keep([1, 2, 3])
        with pytest.raises(pyjs.JSException, match="borrowed proxy"):
            use()
        # ... unless JS gets a lasting proxy
        proxy = pyjs.create_proxy([1, 2, 3])
        keep(proxy)
        assert use() == 1
        proxy.destroy()
        with pytest.raises(pyjs.JSException):
            use()
    finally:
        pyjs.js.Function("delete globalThis.__pyjs_test_kept;")()


def test_python_exception_through_js():
    # a python exception raised in a callback called by JS arrives as the
    # original exception, not as a JS error
    def fail():
        raise KeyError("through js")

    call = pyjs.js.Function("f", "return f();")
    with pytest.raises(KeyError, match="through js"):
        call(fail)


def test_getitem_errors():
    array = eval_jsfunc("[1, 2, 3]")
    assert array[0] == 1
    assert array[-1] == 3
    with pytest.raises(IndexError):
        array[3]
    js_map = eval_jsfunc("new Map([[1, 'one']])")
    assert js_map[1] == "one"
    with pytest.raises(KeyError):
        js_map[2]
    # a plain object is no container: its properties are attributes
    obj = eval_jsfunc("{a: 1}")
    assert obj.a == 1
    with pytest.raises(AttributeError):
        obj.b
    with pytest.raises(TypeError):
        obj["a"]
    with pytest.raises(TypeError):
        obj["a"] = 2


def test_setitem_delitem():
    array = eval_jsfunc("[1, 2, 3]")
    array[0] = 10
    array[-1] = 30
    assert pyjs.to_py(array) == [10, 2, 30]
    with pytest.raises(IndexError):
        array[3] = 4
    del array[0]
    assert pyjs.to_py(array) == [2, 30]

    js_map = eval_jsfunc("new Map()")
    js_map["key"] = "value"
    assert js_map["key"] == "value"
    assert len(js_map) == 1
    del js_map["key"]
    assert len(js_map) == 0

    typed = eval_jsfunc("new Float64Array(2)")
    typed[1] = 1.5
    assert typed[1] == 1.5
    assert typed[-1] == 1.5


def test_del_attr():
    obj = eval_jsfunc(
        """{
        foo : 1,
        bar : "bar",
        foobar : ["foo","bar"]
    }"""
    )

    assert hasattr(obj, "foobar")
    del obj.foobar
    assert not hasattr(obj, "foobar")


def test_del_item():
    js_set = eval_jsfunc("""new Set([1,2,3,"four"])""")

    assert js_set.has(1)
    assert len(js_set) == 4

    # a Set has no get() / set(): it is no mapping, items are removed with
    # its own method
    with pytest.raises(TypeError):
        del js_set[1]
    js_set.delete(1)

    assert not js_set.has(1)
    assert 1 not in js_set
    assert len(js_set) == 3

    js_set.delete("four")

    assert not js_set.has("four")
    assert len(js_set) == 2

def test_cyclic_array():
    from js import Function

    jsf = Function(
        """
        let a = [0,0];
        a[1] = a;
        return a
    """
    )
    obj_with_cycle = jsf()

    py_obj = pyjs.to_py(obj_with_cycle)
    assert py_obj != py_obj[0]
    assert id(py_obj) == id(py_obj[1])


def test_cyclic_obj():
    from js import Function

    jsf = Function(
        """

        let cyclic_array = [0,0];
        cyclic_array[1] = cyclic_array;

        let obj = {
            cyclic_array : cyclic_array,
            b : [1,2, {}]
        }
        obj.b[2] = obj;
        return obj
    """
    )
    obj_with_cycle = jsf()

    py_obj = pyjs.to_py(obj_with_cycle)

    cyclic_array = py_obj["cyclic_array"]
    assert cyclic_array != cyclic_array[0]
    assert id(cyclic_array) == id(cyclic_array[1])

    assert py_obj["b"][0] == 1
    assert py_obj["b"][1] == 2
    assert id(py_obj["b"][2]) == id(py_obj)


def test_implicit_js_to_py_conversion():
    pass


# JS code that throws -> the `name` of the JSException it raises in python
@pytest.mark.parametrize(
    "js_code,name",
    [
        ('throw Error("sorry")', "Error"),
        ("let a = undefinedVariable", "ReferenceError"),
        ("decodeURIComponent('%')", "URIError"),
        ("null.f()", "TypeError"),
        ("new Array(-1)", "RangeError"),
        ('throw new DOMException("gone", "AbortError")', "AbortError"),
        ("class MyError extends Error { constructor(m) { super(m); this.name = 'MyError'; } } throw new MyError('x')",
         "MyError"),
    ],
)
def test_js_exceptions(js_code, name):
    f = pyjs.js.Function(js_code)
    with pytest.raises(pyjs.JSException) as e_info:
        f()
    e = e_info.value
    assert e.name == name
    assert isinstance(e.message, str)
    # (as JavaScript shows an error)
    assert str(e) == f"{e.name}: {e.message}"
    # the JS error object itself
    assert isinstance(e.js_error, pyjs.JSProxy)
    assert e.js_error.name == name
    # a JSException is also a RuntimeError (pyjs raised RuntimeError for
    # rejected promises once)
    assert isinstance(e, RuntimeError)


def test_js_exception_attributes():
    with pytest.raises(pyjs.JSException) as e_info:
        pyjs.js.Function('throw new TypeError("the message")')()
    e = e_info.value
    assert e.name == "TypeError"
    assert e.message == "the message"
    # (what a stack trace looks like differs between browsers)
    assert isinstance(e.stack, str) and e.stack


def test_js_syntax_error():
    # (thrown by creating the function, not by calling it)
    with pytest.raises(pyjs.JSException) as e_info:
        pyjs.js.Function("hoo bar")
    assert e_info.value.name == "SyntaxError"


def test_js_stack_overflow():
    # endless recursion: a RangeError (firefox: InternalError)
    f = pyjs.js.Function("function loop(x) { loop(x + 1); } loop(0);")
    with pytest.raises(pyjs.JSException) as e_info:
        f()
    assert e_info.value.name in ("RangeError", "InternalError")


# JS can throw anything, not only Error objects
@pytest.mark.parametrize(
    "js_code,value",
    [
        ('throw "i_am_not_a_real_exception"', "i_am_not_a_real_exception"),
        ("throw 42", 42),
        ("throw null", None),
        ("throw undefined", None),
    ],
)
def test_js_throws_non_error(js_code, value):
    with pytest.raises(pyjs.JSException) as e_info:
        pyjs.js.Function(js_code)()
    e = e_info.value
    # no name of its own
    assert e.name == "Error"
    assert e.stack is None
    if js_code == "throw null":
        assert e.js_error is pyjs.jsnull
    else:
        assert e.js_error == value


def test_js_throws_plain_object():
    with pytest.raises(pyjs.JSException) as e_info:
        pyjs.js.Function("throw {code: 7, message: 'custom'}")()
    e = e_info.value
    assert e.message == "custom"
    assert e.js_error.code == 7


def test_int_container():
    from js import Function

    jsf = Function(
        """
        return [1,1]
    """
    )
    js_obj = jsf()
    py_obj = pyjs.to_py(js_obj)
    assert py_obj



def test_sleep():
    import time
    start = time.time()
    time.sleep(2)
    end = time.time()

    assert end - start >= 2

    # probably we can also do more precise tests
    # but lets keept it simple for now
    assert end - start < 2.1


def test_imports_sys():
    import termios
    import fcntl
    import pexpect
    import resource


def test_webbrowser():
    from webbrowser import open, open_new, open_new_tab
