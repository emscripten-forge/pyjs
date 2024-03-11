import asyncio
import functools
import json
from pyjs_core import internal, js,JsValue
from .core import new
from .error_handling import JsError, JsGenericError, JsInternalError, JsRangeError, JsReferenceError, JsSyntaxError, JsTypeError, JsURIError
class _JsToPyConverterCache(object):
    def __init__(self):
        self._js_obj_to_int = js.WeakMap.new()
        self._int_to_py_obj = dict()
        self._counter = 0

    def __setitem__(self, js_val, py_val):
        c = self._counter
        self._js_obj_to_int.set(js_val, c)
        self._int_to_py_obj[c] = py_val
        self._counter = c + 1

    def __getitem__(self, js_val):
        if (key := self._js_obj_to_int.get(js_val)) is not None:
            return self._int_to_py_obj[key]
        else:
            return None

    def get(self, js_val, default_py):
        if (key := self._js_obj_to_int.get(js_val)) is not None:
            return self._int_to_py_obj[key], True
        else:
            self[js_val] = default_py
            return default_py, False

def array_converter(js_val, depth, cache, converter_options):
    py_list, found_in_cache = cache.get(js_val, [])
    if found_in_cache:
        return py_list

    size = internal.length(js_val)
    for i in range(size):
        # js_item = internal.__getitem__(js_val, i)
        js_item = js_val[i]
        py_item = to_py(
            js_item, depth=depth + 1, cache=cache, converter_options=converter_options
        )
        py_list.append(py_item)
    return py_list

def object_converter(js_val, depth, cache, converter_options):

    ret_dict, found_in_cache = cache.get(js_val, {})
    if found_in_cache:
        return ret_dict

    keys = internal.object_keys(js_val)
    values = internal.object_values(js_val)
    size = internal.length(keys)

    for i in range(size):

        # # todo, keys are always strings, this allows for optimization
        py_key = keys[i]
        js_val = values[i]

        py_val = to_py(
            js_val, depth=depth + 1, cache=cache, converter_options=converter_options
        )

        ret_dict[py_key] = py_val

    return ret_dict

def map_converter(js_val, depth, cache, converter_options):

    ret_dict, found_in_cache = cache.get(js_val, {})
    if found_in_cache:
        return ret_dict

    keys = js.Array["from"](js_val.keys())
    values = js.Array["from"](js_val.values())
    size = internal.length(keys)

    for i in range(size):

        js_key = keys[i]
        js_val = values[i]

        py_val = to_py(
            js_val, depth=depth + 1, cache=cache, converter_options=converter_options
        )

        py_key = to_py(
            js_key, depth=depth + 1, cache=cache, converter_options=converter_options
        )

        ret_dict[py_key] = py_val

    return ret_dict


def set_converter(js_val, depth, cache, converter_options):
    pyset, found_in_cache = cache.get(js_val, set())
    if found_in_cache:
        return pyset

    for v in js_val:
        pyset.add(
            to_py(v, depth=depth + 1, cache=cache, converter_options=converter_options)
        )
    return pyset


def error_converter(js_val, depth, cache, converter_options, error_cls):
    return error_cls(err=js_val)

error_to_py_converters = dict(
    Error=functools.partial(error_converter, error_cls=JsError),
    InternalError=functools.partial(error_converter, error_cls=JsInternalError),
    RangeError=functools.partial(error_converter, error_cls=JsRangeError),
    ReferenceError=functools.partial(error_converter, error_cls=JsReferenceError),
    SyntaxError=functools.partial(error_converter, error_cls=JsSyntaxError),
    TypeError=functools.partial(error_converter, error_cls=JsTypeError),
    URIError=functools.partial(error_converter, error_cls=JsURIError),
)
# register converters
basic_to_py_converters = {
    "0": lambda x: None,
    "1": lambda x, d, c, opts: None,
    "3": lambda x, d, c, opts: internal.as_string(x),
    "6": lambda x, d, c, opts: internal.as_boolean(x),
    "4": lambda x, d, c, opts: internal.as_int(x),
    "5": lambda x, d, c, opts: internal.as_float(x),
    "pyobject": lambda x, d, c, opts: internal.as_py_object(x),
    "2": object_converter,
    "Object": object_converter,
    "Array": array_converter,
    "Set": set_converter,
    "Map": map_converter,
    "7": lambda x, d, c, opts: x,
    "Promise": lambda x, d, c, opts: x._to_future(),
    "ArrayBuffer": lambda x, d, c, opts: to_py(new(js.Uint8Array, x), d, c, opts),
    "Uint8Array": lambda x, d, c, opts: internal.as_buffer(x),
    "Int8Array": lambda x, d, c, opts: internal.as_buffer(x),
    "Uint16Array": lambda x, d, c, opts: internal.as_buffer(x),
    "Int16Array": lambda x, d, c, opts: internal.as_buffer(x),
    "Uint32Array": lambda x, d, c, opts: internal.as_buffer(x),
    "Int32Array": lambda x, d, c, opts: internal.as_buffer(x),
    "Float32Array": lambda x, d, c, opts: internal.as_buffer(x),
    "Float64Array": lambda x, d, c, opts: internal.as_buffer(x),
    "BigInt64Array": lambda x, d, c, opts: internal.as_buffer(x),
    "BigUint64Array": lambda x, d, c, opts: internal.as_buffer(x),
    "Uint8ClampedArray": lambda x, d, c, opts: internal.as_buffer(x),
}
basic_to_py_converters = {**basic_to_py_converters, **error_to_py_converters}

def register_converter(cls_name, converter):
    basic_to_py_converters[cls_name] = converter


def to_py_json(js_val):
    return json.loads(JSON.stringify(js_val))

class JsToPyConverterOptions(object):
    def __init__(self, json=False, converters=None, default_converter=None):
        self.json = json

        if converters is None:
            converters = basic_to_py_converters
        if default_converter is None:
            default_converter = basic_to_py_converters["Object"]

        self.converters = converters
        self.default_converter = default_converter


def to_py(js_val, depth=0, cache=None, converter_options=None):
    if not isinstance(js_val, JsValue):
        return js_val
    if converter_options is None:
        converter_options = JsToPyConverterOptions()
    if cache is None:
        cache = _JsToPyConverterCache()
    converters = converter_options.converters
    default_converter = converter_options.default_converter
    ts = internal.get_type_string(js_val)
    return converters.get(ts, default_converter)(
        js_val, depth, cache, converter_options
    )

 
def error_to_py(err):
    default_converter = functools.partial(error_converter, error_cls=JsGenericError)
    converter_options = JsToPyConverterOptions(
        converters=error_to_py_converters, default_converter=default_converter
    )
    return to_py(err, converter_options=converter_options)


def error_to_py_and_raise(err):
    raise error_to_py(err)


def buffer_to_js_typed_array(buffer, view=False):
    return internal.py_1d_buffer_to_typed_array(buffer, bool(view))
