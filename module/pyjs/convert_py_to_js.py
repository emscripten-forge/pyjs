
from .core import new
from pyjs_core import JsValue, js_array, js, js_undefined,internal

def _py_list_like_to_js(value, cache, depth, max_depth):
    vid = id(value)
    if vid in cache:
        return cache[vid]
    j_value = js_array()
    cache[vid] = j_value
    for v in value:
        js_v = to_js(v, cache=cache, depth=depth + 1, max_depth=max_depth)
        j_value.push(js_v)
    return j_value


def _py_dict_like_to_js(value, cache, depth, max_depth):
    vid = id(value)
    if vid in cache:
        return cache[vid]
    j_value = new(js.Map)
    cache[vid] = j_value
    for k, v in value.items():
        js_k = to_js(k, cache=cache, depth=depth + 1, max_depth=max_depth)
        js_v = to_js(v, cache=cache, depth=depth + 1, max_depth=max_depth)
        j_value.set(js_k, js_v)
    return j_value


def _py_set_like_to_js(value, cache, depth, max_depth):
    vid = id(value)
    if vid in cache:
        return cache[vid]
    j_value = new(js.Set)
    cache[vid] = j_value
    for v in value:
        js_v = to_js(v, cache=cache, depth=depth + 1, max_depth=max_depth)
        j_value.add(js_v)
    return j_value


def to_js(value, cache=None, depth=0, max_depth=None):
    if cache is None:
        cache = dict()

    if max_depth is not None and depth >= max_depth:
        return value

    if isinstance(value, JsValue):
        return value
    elif isinstance(value, (list, tuple)):
        return _py_list_like_to_js(
            value=value, cache=cache, depth=depth, max_depth=max_depth
        )
    elif isinstance(value, dict):
        return _py_dict_like_to_js(
            value=value, cache=cache, depth=depth, max_depth=max_depth
        )
    elif isinstance(value, set):
        return _py_set_like_to_js(
            value=value, cache=cache, depth=depth, max_depth=max_depth
        )
    elif value is None:
        return js_undefined()
    elif isinstance(value, (int, float, str, bool)):
        return JsValue(value)

    # # bytestring
    elif isinstance(value, bytes):
        return internal.bytes_to_typed_array(value).buffer


    else:
        raise RuntimeError(f"no registerd converted for {value} of type {type(value)}")
