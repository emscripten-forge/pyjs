
from .core import new
from pyjs_core import JsValue, js_array, js, js_undefined,internal

def _py_list_like_to_js(value, cache, depth, max_depth, dict_converter):
    vid = id(value)
    if vid in cache:
        return cache[vid]
    j_value = js_array()
    cache[vid] = j_value
    for v in value:
        js_v = to_js(v, cache=cache, depth=depth + 1, max_depth=max_depth, dict_converter=dict_converter)
        j_value.push(js_v)
    return j_value


def _py_dict_like_to_js(value, cache, depth, max_depth, dict_converter):
    vid = id(value)
    if vid in cache:
        return cache[vid]
    if dict_converter is not None:
        # The converted value is only cached after all entries are converted,
        # so recursive dicts are not supported.
        entries = js_array()
        for k, v in value.items():
            js_k = to_js(k, cache=cache, depth=depth + 1, max_depth=max_depth, dict_converter=dict_converter)
            js_v = to_js(v, cache=cache, depth=depth + 1, max_depth=max_depth, dict_converter=dict_converter)
            pair = js_array()
            pair.push(js_k)
            pair.push(js_v)
            entries.push(pair)
        j_value = dict_converter(entries)
        cache[vid] = j_value
        return j_value
    j_value = new(js.LiteralMap)
    cache[vid] = j_value
    for k, v in value.items():
        js_k = to_js(k, cache=cache, depth=depth + 1, max_depth=max_depth, dict_converter=dict_converter)
        js_v = to_js(v, cache=cache, depth=depth + 1, max_depth=max_depth, dict_converter=dict_converter)
        j_value.set(js_k, js_v)
    return j_value


def _py_set_like_to_js(value, cache, depth, max_depth, dict_converter):
    vid = id(value)
    if vid in cache:
        return cache[vid]
    j_value = new(js.Set)
    cache[vid] = j_value
    for v in value:
        js_v = to_js(v, cache=cache, depth=depth + 1, max_depth=max_depth, dict_converter=dict_converter)
        j_value.add(js_v)
    return j_value


def to_js(value, cache=None, depth=0, max_depth=None, dict_converter=None):
    """
    Convert a Python object to a JavaScript object.

    Args:
        value: The Python object to convert.
        cache: A dictionary to use as a cache for already converted objects.
        depth: The current depth of of nested object conversion.
        max_depth: The maximum depth of nested object conversion.
        dict_converter: Optional function that receives a JavaScript array of
            [key, value] pairs and returns the converted dict, e.g.
            js.Object.fromEntries. If None, dicts are converted to a LiteralMap.
            Recursive dicts are not supported when this is used.

    Returns:

        a JavaScript stored in a pyjs_core.JsValue
    """
    if cache is None:
        cache = dict()

    if max_depth is not None and depth >= max_depth:
        return value

    if isinstance(value, JsValue):
        return value
    elif isinstance(value, (list, tuple)):
        return _py_list_like_to_js(
            value=value, cache=cache, depth=depth, max_depth=max_depth, dict_converter=dict_converter
        )
    elif isinstance(value, dict):
        return _py_dict_like_to_js(
            value=value, cache=cache, depth=depth, max_depth=max_depth, dict_converter=dict_converter
        )
    elif isinstance(value, set):
        return _py_set_like_to_js(
            value=value, cache=cache, depth=depth, max_depth=max_depth, dict_converter=dict_converter
        )
    elif value is None:
        return js_undefined()
    elif isinstance(value, (int, float, str, bool)):
        return JsValue(value)

    # # bytestring
    elif isinstance(value, bytes):
        l = len(value)
        return internal.bytes_to_typed_array(value, l).buffer

    elif hasattr(value, "explicit_to_js"):
        return value.explicit_to_js()

    elif hasattr(value, "implicit_to_js"):
        return value.implicit_to_js()

    else:
        raise RuntimeError(f"no registerd converted for {value} of type {type(value)}")
