import pytest
import os
import pyjs
import numpy
import types
import operator
import json

def nullary(body):
    return pyjs.js.Function(body)()

def eval(body):
    return pyjs.js.Function("return "+body)()


def test_js_submodule():
    from pyjs.js import Function
    assert Function('return "hello_world"')() == "hello_world"

def test_js_function_creation():
    f = pyjs.js.Function("arg0","""
        return "hello_" + arg0
    """)
    ret = f("world")
    assert ret == "hello_world"


def array_eq(x, should):
    return x.dtype == should.dtype and numpy.array_equal(x, should)

def array_feq(x, should):
    return x.dtype == should.dtype and numpy.allclose(x, should)

def nested_eq(x, should):
    # stupid low effort impls

    x_string = json.dumps(x, sort_keys=True, indent=2)
    should_string = json.dumps(should, sort_keys=True, indent=2)
    return x_string == should_string

@pytest.mark.parametrize("test_input,expected_type,expected_value,comperator", [

    # atomic items
    ("undefined",   types.NoneType, None,   (lambda x,should_val: x is None)),
    ("42",          int,            42,     operator.eq),
    ("17.5",        float,          17.5,   operator.eq),
    ("false",       bool,           False,  operator.eq),
    ("true",        bool,           True,   operator.eq),
    ("42",          int,            42,     operator.eq),
    ("42",          int,            42,     operator.eq),
    # arrays
    ("new Uint8Array([1,2,3])",  numpy.ndarray, numpy.array([1,2,3],  dtype='uint8'), array_eq),
    ("new Int8Array([-1,2,-3])", numpy.ndarray, numpy.array([-1,2,-3], dtype='int8'), array_eq),
    ("new Uint16Array([1,2,300])",  numpy.ndarray, numpy.array([1,2,300],  dtype='uint16'), array_eq),
    ("new Int16Array([-1,2,-300])", numpy.ndarray, numpy.array([-1,2,-300], dtype='int16'), array_eq),
    ("new Uint32Array([1,2,300])",  numpy.ndarray, numpy.array([1,2,300],  dtype='uint32'), array_eq),
    ("new Int32Array([-1,2,-300])", numpy.ndarray, numpy.array([-1,2,-300], dtype='int32'), array_eq),
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
    py_val = pyjs.to_py(eval(test_input))
    assert isinstance(py_val, expected_type)
    assert comperator(py_val, expected_value)







# def test_to_py():
#     js_object = eval("""{
#         _null         : null,
#         _undefined    : undefined,
#         _int          : 42,
#         _float        : 1.5,
#         _bool         : true,
#         _function     : function(){ },
#         _uin8t_array  : new Uint8Array([0,2,4,8]),
#         _uin8t_array  : new Int8Array([-2,-1,0,1,2])   
#     }""")

#     py_object = pyjs.to_py(js_object)

#     assert py_object['_null'] is None

#     assert py_object['_undefined'] is None

#     assert isinstance(py_object['_int'], int) 
#     assert py_object['_int'] == 42 

#     assert isinstance(py_object['_float'], float) 
#     assert py_object['_float'] == 1.5

#     assert isinstance(py_object['_bool'], bool) 
#     assert py_object['_bool'] == True




os.environ["NO_COLOR"] = "1"
retcode = pytest.main(["-s", "/script/test_pyjs.py"])
