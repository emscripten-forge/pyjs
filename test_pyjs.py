import pytest
import os
import pyjs
import numpy
import types
import operator
import json
from types import NoneType

def nullary(body):
    return pyjs.js.Function(body)()

def eval(body):
    return pyjs.js.Function("return "+body)()

def ensure_js(val):
    if not isinstance(val, pyjs.JsValue):
        if not isinstance(val, str):
            return pyjs.JsValue(val)
        else:
            return eval(val)
    else:
        return val


def array_eq(x, should):
    return x.dtype == should.dtype and numpy.array_equal(x, should)

def array_feq(x, should):
    return x.dtype == should.dtype and numpy.allclose(x, should)

def nested_eq(x, should):
    # stupid low effort impls

    x_string = json.dumps(x, sort_keys=True, indent=2)
    should_string = json.dumps(should, sort_keys=True, indent=2)
    return x_string == should_string





def test_js_submodule():
    from pyjs.js import Function
    assert Function('return "hello_world"')() == "hello_world"

def test_js_function_creation():
    f = pyjs.js.Function("arg0","""
        return "hello_" + arg0
    """)
    ret = f("world")
    assert ret == "hello_world"


def test_create_once_callable_nullary():
    def pyfunc():
        return "hello_from_pyfunc"

    js_once_callable = pyjs.create_once_callable(pyfunc)

    # call the first time
    ret  = js_once_callable()
    assert pyjs.to_py(ret) == "hello_from_pyfunc"
    ret.delete()

    with pytest.raises(Exception) as e_info:
        # call the second time
        ret  = js_once_callable()

    with pytest.raises(Exception) as e_info:
        # call the third time
        ret  = js_once_callable()



def test_callable_context():

    def pyfunc():
        return "hello_from_pyfunc"

    with pyjs.callable_context(pyfunc) as js_cb:
        ret = js_cb()
        assert pyjs.to_py(ret) == "hello_from_pyfunc"
        ret.delete()


def test_callable():

    def pyfunc():
        return "hello_from_pyfunc"

    js_cb, cleanup = pyjs.create_callable(pyfunc)

    ret = js_cb()
    assert pyjs.to_py(ret) == "hello_from_pyfunc"
    ret.delete()

    cleanup.delete()


@pytest.mark.parametrize("test_input,expected_type,expected_value,comperator", [

    # special items
    ("undefined",   NoneType,  None,        (lambda x,should_val: x is None)),

    # basic items
    ("42",          int,       42,          operator.eq),
    ("-42",         int,       -42,         operator.eq),
    ("17.5",        float,     17.5,        operator.eq),
    ("false",       bool,      False,       operator.eq),
    ("true",        bool,      True,        operator.eq),

    # various strings
    ('"42"',        str,      "42",         operator.eq),
    ('""',          str,      "",           operator.eq),
    ('"undefined"', str,      "undefined",  operator.eq),
    ('"null"',      str,      "null",       operator.eq),

    # set
    ("new Set([1,2,5])",set,set([1,2,5]), operator.eq),
    # arrays
    ("new Uint8Array([1,2,3])",  numpy.ndarray, numpy.array([1,2,3],        dtype='uint8'),  array_eq),
    ("new Int8Array([-1,2,-3])", numpy.ndarray, numpy.array([-1,2,-3],      dtype='int8'),   array_eq),
    ("new Uint16Array([1,2,300])",  numpy.ndarray, numpy.array([1,2,300],   dtype='uint16'), array_eq),
    ("new Int16Array([-1,2,-300])", numpy.ndarray, numpy.array([-1,2,-300], dtype='int16'),  array_eq),
    ("new Uint32Array([1,2,300])",  numpy.ndarray, numpy.array([1,2,300],   dtype='uint32'), array_eq),
    ("new Int32Array([-1,2,-300])", numpy.ndarray, numpy.array([-1,2,-300], dtype='int32'),  array_eq),

    # floating point arrays
    ("new Float32Array([-10.5,0.0, 1.55])",  numpy.ndarray, numpy.array([-10.5,0.0, 1.55],  dtype='float32'), array_feq),
    ("new Float64Array([-10.5,0.0, 1.55])",  numpy.ndarray, numpy.array([-10.5,0.0, 1.55],  dtype='float64'), array_feq),

    # functions
    ("function(){}",  pyjs.JsValue, None, (lambda x,y:True)),

    # nested objects
    ('[1,2,"three"]', list,         [1,2,"three"], nested_eq),
    ('{ foo : { bar:1 }, fobar: [1,1,2] }', dict, { "foo" : { "bar":1 }, "fobar": [1,1,2]}, nested_eq),

])
def test_to_py(test_input, expected_type, expected_value, comperator):
    py_val = pyjs.to_py(ensure_js(test_input))
    assert isinstance(py_val, expected_type)
    assert comperator(py_val, expected_value)


@pytest.mark.parametrize("test_input,expected_output", [
    ("42",   "42"),
    ("{}",   "[object Object]"),
    ("[1, 2, 3]",   "1,2,3")
])
def test_to_str(test_input, expected_output):
    as_str = str(ensure_js(test_input))
    assert as_str == expected_output


@pytest.mark.parametrize("test_input,expected_output", [
    #("[]",0),
    ("[0]",1),
    ("[0,1,2]",3),
    ("[[1,1,2,3],1,2]",3),
    #("{}",0),
    #("{foo:1}",1),
    (pyjs.JsValue("some_string"),11)
])
def test_len(test_input, expected_output):
    assert len(ensure_js(test_input)) == expected_output



@pytest.mark.parametrize("container,query,expected_output", [
    ("[1,2,3]",pyjs.JsValue("1"),False),
    ('["1",2,3]',pyjs.JsValue("1"),True),
    ("[1,2,3]",pyjs.JsValue(1),True),
    ("[1,2,3]",pyjs.JsValue("4"),False),
])
def test_contains(container, query, expected_output):
    assert ( ensure_js(query) in ensure_js(container)) == expected_output


@pytest.mark.parametrize("a,b,out", [
    (pyjs.JsValue(""),   pyjs.JsValue(""),    True),
    (pyjs.JsValue(""),   pyjs.JsValue("a"),   False),
    (pyjs.JsValue("b"),  pyjs.JsValue("a"),   False),
    (pyjs.JsValue("a"),  pyjs.JsValue("a"),   True),
    (pyjs.JsValue("1"),  pyjs.JsValue(1),     False),
    (pyjs.JsValue(1),    pyjs.JsValue(1),     True),
    (pyjs.JsValue(0),    pyjs.JsValue(1),     False),
])
def test_eq(a, b, out):
    assert (ensure_js(a) == ensure_js(b)) == out



def test_array_iterator():
    array = eval('[1,2,"three"]')
    py_array = [pyjs.to_py(v) for v in array]
    assert len(py_array) == 3
    assert py_array == [1,2,"three"]

    # make sure that elements of iterator
    # are still js values
    array = eval('[{fo:"bar"}]')
    element = next(iter(array))
    assert element.typeof == "object"

def test_custom_converter():
    rectangle = pyjs.js.Function("""
        class Rectangle {
          constructor(height, width) {
            this.height = height;
            this.width = width;
          }
        }
        return new Rectangle(10,20)
    """)()

    r = pyjs.to_py(rectangle)
    assert isinstance(r, dict)
    assert r['height'] == 10
    assert r['width'] == 20

    class Rectangle(object):
        def __init__(self, height, width):
            self.height = height
            self.width = width

    def rectangle_converter(js_val,  depth=0, converter_options=None):
        return Rectangle(js_val.height, js_val.width)

    pyjs.register_converter('Rectangle',rectangle_converter)

    r = pyjs.to_py(rectangle)
    assert isinstance(r, Rectangle)
    assert r.height == 10
    assert r.width == 20




def test_del_attr():
    obj = eval("""{
        foo : 1,
        bar : "bar",
        foobar : ["foo","bar"]
    }""")

    assert hasattr(obj,"foobar")
    del obj.foobar
    assert not hasattr(obj,"foobar")


def test_del_item():
    js_set = eval("""new Set([1,2,3,"four"])""")

    assert js_set.has(1)
    assert len(js_set) == 4

    del js_set[1]

    assert not js_set.has(1)
    assert len(js_set) == 3

    del js_set["four"]

    assert not js_set.has("four")
    assert len(js_set) == 2



def test_np_array():
    view = pyjs.js.Function("""
        var buffer = new ArrayBuffer(8);
        var view_c   = new Uint8Array(buffer);
        for (let i = 0; i < view_c.length; i++) {
            view_c[i] = i;
        }
        return new Uint8Array(buffer, 4,2);
    """)()

    assert array_eq(pyjs.to_py(view), numpy.array([4,5], dtype='uint8'))


if __name__ == "__main__":


    # start the tests
    os.environ["NO_COLOR"] = "1"
    retcode = pytest.main(["-s","/script/test_pyjs.py"])
