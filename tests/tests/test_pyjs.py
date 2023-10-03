import json
import operator
import os
from types import NoneType
import asyncio

try:
    import numpy
    has_numpy = True
except ImportError:
    has_numpy = False



import pytest

from .conftest import *

import pyjs


def test_js_submodule():
    from pyjs.js import Function

    assert Function('return "hello_world"')() == "hello_world"


def test_js_function_creation():
    f = pyjs.js.Function(
        "arg0",
        """
        return "hello_" + arg0
    """,
    )
    ret = f("world")
    assert ret == "hello_world"


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


def test_callable_context():
    def pyfunc():
        return "hello_from_pyfunc"

    with pyjs.callable_context(pyfunc) as js_cb:
        ret = js_cb()
        assert ret == "hello_from_pyfunc"


def test_callable():
    def pyfunc():
        return "hello_from_pyfunc"

    js_cb, cleanup = pyjs.create_callable(pyfunc)

    ret = js_cb()
    assert ret == "hello_from_pyfunc"

    cleanup.delete()


def test_interal_type_str():
    assert pyjs.internal.get_type_string(pyjs.JsValue(True)) == "6"
    assert pyjs.internal.get_type_string(pyjs.JsValue(1)) == "4"
    assert pyjs.internal.get_type_string(pyjs.JsValue(1.5)) == "5"
    assert pyjs.internal.get_type_string(pyjs.JsValue("1")) == "3"
    assert pyjs.internal.get_type_string(pyjs.JsValue([1, 2, 3])) == "pyobject"


parameters = [
    # special items
    ("undefined", NoneType, None, (lambda x, should_val: x is None)),
    ("null", NoneType, None, (lambda x, should_val: x is None)),
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
    ("function(){}", pyjs.JsValue, None, (lambda x, y: True)),
    # nested objects
    ('[1,2,"three"]', list, [1, 2, "three"], nested_eq),
    (
        "{ foo : { bar:1 }, fobar: [1,1,2] }",
        dict,
        {"foo": {"bar": 1}, "fobar": [1, 1, 2]},
        nested_eq,
    ),
]

if has_numpy:
    parameters += [
        # arrays
        (
            "new Uint8Array([1,2,3])",
            pyjs.TypedArrayBuffer,
            numpy.array([1, 2, 3], dtype="uint8"),
            converting_array_eq,
        ),
        (
            "new Int8Array([-1,2,-3])",
            pyjs.TypedArrayBuffer,
            numpy.array([-1, 2, -3], dtype="int8"),
            converting_array_eq,
        ),
        (
            "new Uint16Array([1,2,300])",
            pyjs.TypedArrayBuffer,
            numpy.array([1, 2, 300], dtype="uint16"),
            converting_array_eq,
        ),
        (
            "new Int16Array([-1,2,-300])",
            pyjs.TypedArrayBuffer,
            numpy.array([-1, 2, -300], dtype="int16"),
            converting_array_eq,
        ),
        (
            "new Uint32Array([1,2,300])",
            pyjs.TypedArrayBuffer,
            numpy.array([1, 2, 300], dtype="uint32"),
            converting_array_eq,
        ),
        (
            "new Int32Array([-1,2,-300])",
            pyjs.TypedArrayBuffer,
            numpy.array([-1, 2, -300], dtype="int32"),
            converting_array_eq,
        ),
        # floating point arrays
        (
            "new Float32Array([-10.5,0.0, 1.55])",
            pyjs.TypedArrayBuffer,
            numpy.array([-10.5, 0.0, 1.55], dtype="float32"),
            converting_array_feq,
        ),
        (
            "new Float64Array([-10.5,0.0, 1.55])",
            pyjs.TypedArrayBuffer,
            numpy.array([-10.5, 0.0, 1.55], dtype="float64"),
            converting_array_feq,
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
        {1: [1, 2], "two": {1: [1, 2, "three"]}},
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
    pydict = {1: "a"}
    jsmap = pyjs.to_js(pydict)
    assert jsmap.keys().next().value == 1
    assert jsmap.values().next().value == "a"

    assert jsmap.get(1) == "a"


def test_to_js_none():

    jsval = pyjs.to_js(None)
    assert pyjs._module._is_undefined(jsval)


@pytest.mark.parametrize(
    "test_input,expected_output",
    [
        (lambda: "42", "42"),
        (lambda: "{}", "[object Object]"),
        (lambda: "[1, 2, 3]", "1,2,3"),
        (lambda: pyjs.js_null(), "null"),
        (lambda: pyjs.js_undefined(), "undefined"),
    ],
)
def test_to_str(test_input, expected_output):

    j_test_input = ensure_js(test_input())
    as_str = str(j_test_input)
    assert isinstance(as_str, str)
    assert as_str == expected_output


def test_print_js_null():
    assert str(ensure_js(pyjs.js_null())) == "null"
    assert pyjs.js_null().__str__() == "null"
    assert pyjs.js_null().__repr__() == "null"
    assert isinstance(pyjs.js_null(), pyjs.JsValue)


def test_print_js_undefined():
    assert str(ensure_js(pyjs.js_undefined())) == "undefined"
    assert pyjs.js_undefined().__str__() == "undefined"
    assert pyjs.js_undefined().__repr__() == "undefined"
    assert isinstance(pyjs.js_undefined(), pyjs.JsValue)


@pytest.mark.parametrize(
    "test_input,expected_output",
    [
        # ("[]",0),
        ("[0]", 1),
        ("[0,1,2]", 3),
        ("[[1,1,2,3],1,2]", 3),
        # ("{}",0),
        # ("{foo:1}",1),
        (pyjs.JsValue("some_string"), 11),
    ],
)
def test_len(test_input, expected_output):
    assert len(ensure_js(test_input)) == expected_output


@pytest.mark.parametrize(
    "container,query,expected_output",
    [
        ("[1,2,3]", pyjs.JsValue("1"), False),
        ('["1",2,3]', pyjs.JsValue("1"), True),
        ("[1,2,3]", pyjs.JsValue(1), True),
        ("[1,2,3]", pyjs.JsValue("4"), False),
    ],
)
def test_contains(container, query, expected_output):
    assert (ensure_js(query) in ensure_js(container)) == expected_output


@pytest.mark.parametrize(
    "a,b,out",
    [
        (pyjs.JsValue(""), pyjs.JsValue(""), True),
        (pyjs.JsValue(""), pyjs.JsValue("a"), False),
        (pyjs.JsValue("b"), pyjs.JsValue("a"), False),
        (pyjs.JsValue("a"), pyjs.JsValue("a"), True),
        (pyjs.JsValue("1"), pyjs.JsValue(1), False),
        (pyjs.JsValue(1), pyjs.JsValue(1), True),
        (pyjs.JsValue(0), pyjs.JsValue(1), False),
    ],
)
def test_eq(a, b, out):
    assert (ensure_js(a) == ensure_js(b)) == out


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

    r = pyjs.to_py(rectangle)
    assert isinstance(r, dict)
    assert r["height"] == 10
    assert r["width"] == 20

    class Rectangle(object):
        def __init__(self, height, width):
            self.height = height
            self.width = width

    def rectangle_converter(js_val, depth, cache, converter_options):
        return Rectangle(js_val.height, js_val.width)

    pyjs.register_converter("Rectangle", rectangle_converter)

    r = pyjs.to_py(rectangle)
    assert isinstance(r, Rectangle)
    assert r.height == 10
    assert r.width == 20


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

    del js_set[1]

    assert not js_set.has(1)
    assert len(js_set) == 3

    del js_set["four"]

    assert not js_set.has("four")
    assert len(js_set) == 2

if has_numpy:
    def test_np_array():
        view = pyjs.js.Function(
            """
            var buffer = new ArrayBuffer(8);
            var view_c   = new Uint8Array(buffer);
        for (let i = 0; i < view_c.length; i++) {
                view_c[i] = i;
            }
            return new Uint8Array(buffer, 4,2);
        """
        )()

        assert array_eq(numpy.array(pyjs.to_py(view), copy=True), numpy.array([4, 5], dtype="uint8"))


def test_cyclic_array():
    from pyjs.js import Function

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
    from pyjs.js import Function

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


def test_js_execptions():

    # basic error
    f = pyjs.js.Function(
        """
        throw Error("sorry")
    """
    )

    with pytest.raises(pyjs.JsException) as e_info:
        f()
    with pytest.raises(pyjs.JsError) as e_info:
        f()

    # reference error
    f = pyjs.js.Function(
        """
        let a = undefinedVariable
    """
    )
    with pytest.raises(pyjs.JsException) as e_info:
        f()
    with pytest.raises(pyjs.JsReferenceError) as e_info:
        f()

    # syntax error=
    with pytest.raises(pyjs.JsException) as e_info:
        pyjs.js.Function(
            """
            hoo bar
        """
        )
    with pytest.raises(pyjs.JsSyntaxError) as e_info:
        pyjs.js.Function(
            """
            hoo bar
        """
        )

    # uri error
    f = pyjs.js.Function(
        """
        decodeURIComponent('%')
    """
    )
    with pytest.raises(pyjs.JsException) as e_info:
        f()
    with pytest.raises(pyjs.JsURIError) as e_info:
        f()

    # type error
    f = pyjs.js.Function(
        """
        null.f()
    """
    )
    with pytest.raises(pyjs.JsException) as e_info:
        f()
    with pytest.raises(pyjs.JsTypeError) as e_info:
        f()

    # internal error
    f = pyjs.js.Function(
        """
        function loop(x) {
          if (x >= 1000000000000)
            return;
          // do stuff
          loop(x + 1);
        }
        loop(0);

    """
    )
    with pytest.raises(pyjs.JsException) as e_info:
        f()
    with pytest.raises((pyjs.JsRangeError, pyjs.JsInternalError)) as e_info:
        f()

    # throw a string on js side
    f = pyjs.js.Function(
        """
        throw "i_am_not_a_real_exception"
    """
    )

    with pytest.raises(pyjs.JsGenericError) as e_info:
        f()
    assert pyjs.to_py(e_info.value.value) == "i_am_not_a_real_exception"


def test_int_container():
    from pyjs.js import Function

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

    open("google.com")
    open_new("google.com")
    open_new_tab("google.com")
