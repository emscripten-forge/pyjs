#include "pyjs/macro_magic.hpp"
BEGIN_PYTHON_INIT(pyjs_convert) R"pycode(#"


import json
import numpy
import sys
import types
import contextlib
from typing import Any
import asyncio


class JsToPyConverterOptions(object):
    def __init__(self, json=False):
        self.json = json


def _build_in_to_python(val):
    if val is None:
        return None
    ts = type_str(val)
    if ts in ['string', 'boolean','number','undefined']:
        return to_py(val)
    return val


def array_converter(js_val, depth=0, converter_options=None):
    size = internal.length(js_val)
    py_list = []
    for i in range(size):
        js_item = internal.__getitem__(js_val, i)
        py_item = to_py(js_item, depth=depth+1, converter_options=converter_options)
        py_list.append(py_item)
    return py_list

def object_converter(js_val, depth=0, converter_options=None):
    keys = internal.object_keys(js_val)
    values = internal.object_values(js_val)

    ret_dict = {}
    size = internal.length(keys)

    for  i in range(size):

        js_key = internal.__getitem__(keys,   i)
        js_val = internal.__getitem__(values, i)

        py_key = to_py(js_key, depth=depth+1, converter_options=converter_options)
        py_val = to_py(js_val, depth=depth+1, converter_options=converter_options) 
        
        ret_dict[py_key] = py_val

    return ret_dict


def set_converter(js_val, depth=0, converter_options=None):
    pyset = set()
    for v in js_val:
        pyset.add( to_py(v, depth=depth+1, converter_options=converter_options))
    return pyset

# register converters
_converters = dict(
    null=lambda x:None,
    undefined=lambda x,d,opts:None,
    string=lambda x,d,opts: internal.as_string(x),
    boolean=lambda x,d,opts: internal.as_boolean(x),
    integer=lambda x,d,opts: internal.as_int(x),
    float=lambda x,d,opts: internal.as_float(x),
    pyobject=lambda x,d,opts: internal.as_py_object(x),
    object=object_converter,
    Object=object_converter,
    Array=array_converter,
    Set=set_converter,
    function=lambda x,d,opts:x,
    Promise=lambda x,d,opts: x._to_future(),
    # this is a bit ugly at since `as_numpy_array`
    # has to do the dispatching again
    ArrayBuffer=lambda x,d,opts:   to_py(new(js.Uint8Array, x), d,opts),
    Uint8Array=lambda x,d,opts:    internal.as_numpy_array(x),
    Int8Array =lambda x,d,opts:    internal.as_numpy_array(x),
    Uint16Array=lambda x,d,opts:   internal.as_numpy_array(x),
    Int16Array =lambda x,d,opts:   internal.as_numpy_array(x),
    Uint32Array=lambda x,d,opts:   internal.as_numpy_array(x),
    Int32Array =lambda x,d,opts:   internal.as_numpy_array(x),
    Float32Array=lambda x,d,opts:  internal.as_numpy_array(x),
    Float64Array =lambda x,d,opts: internal.as_numpy_array(x),
    BigInt64Array=lambda x,d,opts:  internal.as_numpy_array(x),
    BigUint64Array =lambda x,d,opts: internal.as_numpy_array(x),
    Uint8ClampedArray=lambda x,d,opts: internal.as_numpy_array(x)
)

def register_converter(cls_name, converter):
    _converters[cls_name] = converter


def to_py_json(js_val):
    return json.loads(JSON.stringify(js_val))


def to_py(js_val,  depth=0, converter_options=None):
    if not isinstance(js_val, JsValue):
        return js_val
    ts = internal.get_type_string(js_val)
    return _converters.get(ts, _converters['object'])(js_val, depth, converter_options)




IN_BROWSER = not to_py(internal.module_property('_IS_NODE'))

#)pycode"
END_PYTHON_INIT
