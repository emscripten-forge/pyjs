import pyjs
import json
import numpy


js_assert_eq = pyjs.js.Function(
    "output",
    "expected_output",
    """
    let eq = output === expected_output;
    if(!eq){
        console.log("assertion failed:", output,"!=",expected_output)
    }
    return eq
""",
)


def to_js_to_py(x):
    return pyjs.to_py(pyjs.to_js(x))


def nullary(body):
    return pyjs.js.Function(body)()


def eval_jsfunc(body):
    return pyjs.js.Function("return " + body)()


def ensure_js(val):
    if not isinstance(val, pyjs.JsValue):
        if not isinstance(val, str):
            return pyjs.JsValue(val)
        else:
            return eval_jsfunc(val)
    else:
        return val


def converting_array_eq(x, should):
    return array_eq(numpy.array(x), should)

def converting_array_feq(x, should):
    return array_feq(numpy.array(x), should)

def array_eq(x, should):
    return x.dtype == should.dtype and numpy.array_equal(x, should)


def array_feq(x, should):
    return x.dtype == should.dtype and numpy.allclose(x, should)


def nested_eq(x, should):
    # stupid low effort impls

    x_string = json.dumps(x, sort_keys=True, indent=2)
    should_string = json.dumps(should, sort_keys=True, indent=2)
    return x_string == should_string
